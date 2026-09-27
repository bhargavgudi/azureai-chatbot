import os
import json
import base64
import requests
from typing import Any, Dict


# ============================================================
# AZURE IMPORTS
# ============================================================

from azure.identity import DefaultAzureCredential

from azure.ai.projects import AIProjectClient

from azure.ai.projects.models import (
    PromptAgentDefinition,
    FunctionTool,
)

# IMPORTANT:
# ResourceManagementClient must be imported from the
# .resources module with the current azure-mgmt-resource package.
from azure.mgmt.resource.resources import ResourceManagementClient

from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import (
    NetworkInterface,
    NetworkInterfaceIPConfiguration,
    Subnet,
    PublicIPAddress,
)
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.models import (
    HardwareProfile,
    StorageProfile,
    ImageReference,
    OSDisk,
    ManagedDiskParameters,
    OSProfile,
    LinuxConfiguration,
    NetworkProfile,
    NetworkInterfaceReference,
    VirtualMachine,
)


from azure.core.exceptions import HttpResponseError


# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ENDPOINT = os.getenv(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://sai-demo.services.ai.azure.com/api/projects/proj-default",
)

AGENT_NAME = os.getenv(
    "FOUNDRY_AGENT_NAME",
    "azure-resource-creator-Agent",
)

DEPLOYMENT_NAME = os.getenv(
    "FOUNDRY_MODEL",
    "gpt-5.4-mini",
)

SUBSCRIPTION_ID = os.getenv(
    "AZURE_SUBSCRIPTION_ID",
    "5f3e512d-9103-4839-b2dc-7efa238f2383",
)


# ============================================================
# JIRA CONFIGURATION
# ============================================================

JIRA_BASE_URL = os.getenv(
    "JIRA_BASE_URL",
    "",
).rstrip("/")

JIRA_EMAIL = os.getenv(
    "JIRA_EMAIL",
    "",
)

JIRA_API_TOKEN = os.getenv(
    "JIRA_API_TOKEN",
    "",
)

JIRA_PROJECT_KEY = os.getenv(
    "JIRA_PROJECT_KEY",
    "",
)


# ============================================================
# AUTHENTICATION
# ============================================================

credential = DefaultAzureCredential()


# ============================================================
# AZURE CLIENTS
# ============================================================

resource_client = ResourceManagementClient(
    credential=credential,
    subscription_id=SUBSCRIPTION_ID,
)

compute_client = ComputeManagementClient(
    credential=credential,
    subscription_id=SUBSCRIPTION_ID,
)

network_client = NetworkManagementClient(
    credential=credential,
    subscription_id=SUBSCRIPTION_ID,
)


# ============================================================
# FOUNDRY CLIENT
# ============================================================

project_client = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=credential,
)


# ============================================================
# UTILITY
# ============================================================

def safe_error_message(error: Exception) -> str:
    message = str(error)

    if JIRA_API_TOKEN:
        message = message.replace(
            JIRA_API_TOKEN,
            "********",
        )

    return message


# ============================================================
# JIRA HEADERS
# ============================================================

def jira_headers() -> Dict[str, str]:

    credentials = (
        f"{JIRA_EMAIL}:{JIRA_API_TOKEN}"
    )

    encoded = base64.b64encode(
        credentials.encode("utf-8")
    ).decode("utf-8")

    return {
        "Authorization": f"Basic {encoded}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# ============================================================
# JIRA CONFIGURATION CHECK
# ============================================================

def check_jira_configuration():

    missing = []

    if not JIRA_BASE_URL:
        missing.append("JIRA_BASE_URL")

    if not JIRA_EMAIL:
        missing.append("JIRA_EMAIL")

    if not JIRA_API_TOKEN:
        missing.append("JIRA_API_TOKEN")

    if not JIRA_PROJECT_KEY:
        missing.append("JIRA_PROJECT_KEY")

    return {
        "configured": len(missing) == 0,
        "missing": missing,
    }


# ============================================================
# JIRA CREATE
# ============================================================

def create_jira_issue(
    summary: str,
    description: str,
    issue_type: str = "Task",
) -> Dict[str, Any]:

    config = check_jira_configuration()

    if not config["configured"]:
        return {
            "success": False,
            "error": "JiraConfigurationMissing",
            "message": (
                "Jira is not configured. Missing: "
                + ", ".join(config["missing"])
            ),
        }

    if not summary:
        return {
            "success": False,
            "error": "MissingParameter",
            "message": "Jira summary is required.",
        }

    try:

        url = (
            f"{JIRA_BASE_URL}"
            "/rest/api/3/issue"
        )

        payload = {
            "fields": {
                "project": {
                    "key": JIRA_PROJECT_KEY,
                },
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": description,
                                }
                            ],
                        }
                    ],
                },
                "issuetype": {
                    "name": issue_type,
                },
            }
        }

        print("[Jira] Creating issue...")

        response = requests.post(
            url,
            headers=jira_headers(),
            json=payload,
            timeout=30,
        )

        if response.status_code not in (200, 201):
            return {
                "success": False,
                "error": "JiraAPIError",
                "status_code": response.status_code,
                "message": response.text,
            }

        data = response.json()

        issue_key = data.get("key")
        issue_id = data.get("id")

        return {
            "success": True,
            "issue_key": issue_key,
            "issue_id": issue_id,
            "issue_url": (
                f"{JIRA_BASE_URL}/browse/{issue_key}"
            ),
            "message": (
                f"Jira issue {issue_key} created."
            ),
        }

    except Exception as e:

        return {
            "success": False,
            "error": type(e).__name__,
            "message": safe_error_message(e),
        }


# ============================================================
# JIRA UPDATE
# ============================================================

def update_jira_issue(
    issue_key: str,
    description: str,
) -> Dict[str, Any]:

    config = check_jira_configuration()

    if not config["configured"]:
        return {
            "success": False,
            "error": "JiraConfigurationMissing",
            "message": (
                "Jira is not configured. Missing: "
                + ", ".join(config["missing"])
            ),
        }

    if not issue_key:
        return {
            "success": False,
            "error": "MissingParameter",
            "message": "Jira issue key is required.",
        }

    try:

        url = (
            f"{JIRA_BASE_URL}"
            f"/rest/api/3/issue/{issue_key}"
        )

        payload = {
            "fields": {
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": description,
                                }
                            ],
                        }
                    ],
                }
            }
        }

        print(
            f"[Jira] Updating {issue_key}..."
        )

        response = requests.put(
            url,
            headers=jira_headers(),
            json=payload,
            timeout=30,
        )

        if response.status_code not in (200, 204):
            return {
                "success": False,
                "error": "JiraAPIError",
                "status_code": response.status_code,
                "message": response.text,
            }

        return {
            "success": True,
            "issue_key": issue_key,
            "issue_url": (
                f"{JIRA_BASE_URL}/browse/{issue_key}"
            ),
            "message": (
                f"Jira issue {issue_key} updated."
            ),
        }

    except Exception as e:

        return {
            "success": False,
            "error": type(e).__name__,
            "message": safe_error_message(e),
        }


# ============================================================
# RESOURCE GROUP
# ============================================================

def create_resource_group(
    resource_group_name: str,
    location: str,
) -> Dict[str, Any]:

    if not resource_group_name:
        return {
            "success": False,
            "error": "MissingParameter",
            "message": "Resource group name is required.",
        }

    if not location:
        return {
            "success": False,
            "error": "MissingParameter",
            "message": "Location is required.",
        }

    try:

        result = (
            resource_client
            .resource_groups
            .create_or_update(
                resource_group_name,
                {
                    "location": location,
                },
            )
        )

        return {
            "success": True,
            "resource_group_name": result.name,
            "location": result.location,
            "message": (
                f"Resource group '{result.name}' "
                "created successfully."
            ),
        }

    except HttpResponseError as e:

        return {
            "success": False,
            "error": "AzureHttpResponseError",
            "status_code": e.status_code,
            "message": safe_error_message(e),
        }

    except Exception as e:

        return {
            "success": False,
            "error": type(e).__name__,
            "message": safe_error_message(e),
        }


# ============================================================
# VM CREATION
# ============================================================

def create_virtual_machine(
    resource_group_name: str,
    vm_name: str,
    location: str,
    zone: str,
    vnet_name: str,
    subnet_name: str,
    vm_size: str,
    image_publisher: str,
    image_offer: str,
    image_sku: str,
    image_version: str,
    admin_username: str,
    admin_password: str,
    create_public_ip: bool,
) -> Dict[str, Any]:

    # ========================================================
    # VALIDATION
    # ========================================================

    required = {
        "resource_group_name": resource_group_name,
        "vm_name": vm_name,
        "location": location,
        "vnet_name": vnet_name,
        "subnet_name": subnet_name,
        "vm_size": vm_size,
        "image_publisher": image_publisher,
        "image_offer": image_offer,
        "image_sku": image_sku,
        "image_version": image_version,
        "admin_username": admin_username,
        "admin_password": admin_password,
    }

    for name, value in required.items():

        if value is None or (
            isinstance(value, str)
            and not value.strip()
        ):
            return {
                "success": False,
                "error": "MissingParameter",
                "message": (
                    f"Required parameter "
                    f"'{name}' is missing."
                ),
            }

    # ========================================================
    # STEP 1 - CREATE JIRA FIRST
    # ========================================================

    jira_issue = create_jira_issue(
        summary=(
            f"Azure VM Deployment - {vm_name}"
        ),
        description=f"""
Azure VM deployment requested.

VM Name: {vm_name}
Resource Group: {resource_group_name}
Location: {location}
Zone: {zone or "Not specified"}

VNet: {vnet_name}
Subnet: {subnet_name}
VM Size: {vm_size}

Image:
Publisher: {image_publisher}
Offer: {image_offer}
SKU: {image_sku}
Version: {image_version}

Public IP requested: {create_public_ip}

Status: DEPLOYMENT STARTED

The administrator password is intentionally
not stored in Jira.
""",
        issue_type="Task",
    )

    if jira_issue["success"]:

        print(
            f"[Jira] Created "
            f"{jira_issue['issue_key']}"
        )

    else:

        print(
            "[Jira] Could not create ticket:"
        )

        print(jira_issue)

    # ========================================================
    # STEP 2 - AZURE DEPLOYMENT
    # ========================================================

    try:

        # ----------------------------------------------------
        # RESOURCE GROUP
        # ----------------------------------------------------

        print(
            "[Azure] Checking resource group..."
        )

        resource_client.resource_groups.get(
            resource_group_name
        )

        # ----------------------------------------------------
        # VNET
        # ----------------------------------------------------

        print(
            "[Azure] Checking VNet..."
        )

        vnet = (
            network_client
            .virtual_networks
            .get(
                resource_group_name,
                vnet_name,
            )
        )

        # ----------------------------------------------------
        # SUBNET
        # ----------------------------------------------------

        print(
            "[Azure] Checking subnet..."
        )

        subnet = (
            network_client
            .subnets
            .get(
                resource_group_name,
                vnet_name,
                subnet_name,
            )
        )

        print(
            f"[Azure] Subnet ID: {subnet.id}"
        )

        # ====================================================
        # PUBLIC IP
        # ====================================================

        public_ip = None

        if create_public_ip:

            public_ip_name = (
                f"{vm_name}-pip"
            )

            public_ip_parameters = {
                "location": location,
                "sku": {
                    "name": "Standard",
                },
                "public_ip_allocation_method": "Static",
                "public_ip_address_version": "IPv4",
            }

            if zone:
                public_ip_parameters["zones"] = [
                    str(zone)
                ]

            print(
                "[Azure] Creating Public IP..."
            )

            public_ip = (
                network_client
                .public_ip_addresses
                .begin_create_or_update(
                    resource_group_name,
                    public_ip_name,
                    public_ip_parameters,
                )
                .result()
            )

            print(
                f"[Azure] Public IP: "
                f"{public_ip.ip_address}"
            )

        # ====================================================
        # NIC
        # ====================================================

                # ----------------------------------------------------
        # NIC
        # ----------------------------------------------------

        print("\n[5/6] Creating NIC...")

        nic_name = f"{vm_name}-nic"

        # IMPORTANT:
        # ip_configurations belongs to the NIC resource.
        # It does NOT belong to the VM network_profile.

        ip_configuration = NetworkInterfaceIPConfiguration(
            name=f"{vm_name}-ipconfig",
            private_ip_allocation_method="Dynamic",
            private_ip_address_version="IPv4",
            subnet={
                "id": subnet.id,
            },
        )

        if public_ip:
            ip_configuration.public_ip_address = {
                "id": public_ip.id,
            }

        nic_parameters = NetworkInterface(
            location=location,
            ip_configurations=[
                ip_configuration
            ],
        )

        print("\nNIC request:")
        print(
            json.dumps(
                {
                    "location": location,
                    "ip_configurations": [
                        {
                            "name": f"{vm_name}-ipconfig",
                            "private_ip_allocation_method": "Dynamic",
                            "private_ip_address_version": "IPv4",
                            "subnet": {
                                "id": subnet.id
                            },
                            "public_ip_address": (
                                {
                                    "id": public_ip.id
                                }
                                if public_ip
                                else None
                            ),
                        }
                    ],
                },
                indent=2,
            )
        )

        nic = (
            network_client
            .network_interfaces
            .begin_create_or_update(
                resource_group_name,
                nic_name,
                nic_parameters,
            )
            .result()
        )

        print(
            f"[Azure] NIC created: {nic.name}"
        )

        print(
            f"[Azure] NIC ID: {nic.id}"
        )

            # ====================================================
            # IMAGE
            # ====================================================

        image_reference = ImageReference(
                publisher=image_publisher,
                offer=image_offer,
                sku=image_sku,
                version=image_version,
            )

        # ====================================================
        # OS DISK
        # ====================================================

        managed_disk = ManagedDiskParameters(
            storage_account_type="Premium_LRS"
        )

        os_disk = OSDisk(
            name=f"{vm_name}-osdisk",
            create_option="FromImage",
            managed_disk=managed_disk,
            caching="ReadWrite",
        )

        # ====================================================
        # STORAGE PROFILE
        # ====================================================

        storage_profile = StorageProfile(
            image_reference=image_reference,
            os_disk=os_disk,
        )

        # ====================================================
        # HARDWARE PROFILE
        # ====================================================

        hardware_profile = HardwareProfile(
            vm_size=vm_size
        )

        # ====================================================
        # OS PROFILE
        # ====================================================

        linux_configuration = LinuxConfiguration(
            disable_password_authentication=False
        )

        os_profile = OSProfile(
            computer_name=vm_name,
            admin_username=admin_username,
            admin_password=admin_password,
            linux_configuration=linux_configuration,
        )

        # ====================================================
        # VM NETWORK PROFILE
        # ====================================================

        # CRITICAL:
        #
        # There is NO ip_configurations here.
        #
        # The VM only references the NIC.

        network_interface_reference = (
            NetworkInterfaceReference(
                id=nic.id,
                primary=True,
            )
        )

        network_profile = NetworkProfile(
            network_interfaces=[
                network_interface_reference
            ]
        )

        # ====================================================
        # VM MODEL
        # ====================================================

        vm_parameters = VirtualMachine(
            location=location,
            hardware_profile=hardware_profile,
            storage_profile=storage_profile,
            os_profile=os_profile,
            network_profile=network_profile,
        )

        # ====================================================
        # AVAILABILITY ZONE
        # ====================================================

        if zone:
            vm_parameters.zones = [
                str(zone)
            ]

        # ====================================================
        # SAFE DEBUG
        # ====================================================

        print(
            "\n[Azure] VM configuration:"
        )

        print(
            json.dumps(
                {
                    "location": location,
                    "vm_size": vm_size,
                    "image": {
                        "publisher": image_publisher,
                        "offer": image_offer,
                        "sku": image_sku,
                        "version": image_version,
                    },
                    "nic_id": nic.id,
                    "zone": zone or None,
                },
                indent=2,
            )
        )

        # ====================================================
        # CREATE VM
        # ====================================================

        print(
            "[Azure] Starting VM deployment..."
        )

        vm = (
            compute_client
            .virtual_machines
            .begin_create_or_update(
                resource_group_name,
                vm_name,
                vm_parameters,
            )
            .result()
        )

        print(
            f"[Azure] VM created: {vm.name}"
        )

        # ====================================================
        # GET FINAL PUBLIC IP
        # ====================================================

        public_ip_address = None

        if public_ip:

            # Re-read from Azure after VM deployment.
            final_public_ip = (
                network_client
                .public_ip_addresses
                .get(
                    resource_group_name,
                    f"{vm_name}-pip",
                )
            )

            public_ip_address = (
                final_public_ip.ip_address
            )

        # ====================================================
        # JIRA SUCCESS UPDATE
        # ====================================================

        success_description = f"""
Azure VM deployment completed successfully.

VM Name: {vm.name}

Resource Group:
{resource_group_name}

Location:
{location}

Zone:
{zone or "Not specified"}

VM Size:
{vm_size}

VNet:
{vnet_name}

Subnet:
{subnet_name}

NIC:
{nic.name}

NIC ID:
{nic.id}

Public IP:
{public_ip_address or "Not assigned"}

Image:
Publisher: {image_publisher}
Offer: {image_offer}
SKU: {image_sku}
Version: {image_version}

Status:
DEPLOYMENT COMPLETED

The VM administrator password is not stored in Jira.
"""

        jira_update = None

        if jira_issue.get("success"):

            jira_update = update_jira_issue(
                issue_key=jira_issue["issue_key"],
                description=success_description,
            )

        # ====================================================
        # SUCCESS RESPONSE
        # ====================================================

        return {
            "success": True,

            "vm_name": vm.name,

            "resource_group":
                resource_group_name,

            "location":
                location,

            "zone":
                zone,

            "vm_size":
                vm_size,

            "vnet":
                vnet_name,

            "subnet":
                subnet_name,

            "nic":
                nic.name,

            "nic_id":
                nic.id,

            "public_ip":
                public_ip_address,

            "image": {
                "publisher":
                    image_publisher,
                "offer":
                    image_offer,
                "sku":
                    image_sku,
                "version":
                    image_version,
            },

            "jira": {
                "created":
                    jira_issue.get(
                        "success",
                        False,
                    ),

                "issue_key":
                    jira_issue.get(
                        "issue_key"
                    ),

                "issue_url":
                    jira_issue.get(
                        "issue_url"
                    ),

                "updated":
                    (
                        jira_update.get(
                            "success",
                            False,
                        )
                        if jira_update
                        else False
                    ),
            },

            "message":
                (
                    f"VM '{vm.name}' "
                    "was created successfully."
                ),
        }

    # ========================================================
    # AZURE HTTP ERROR
    # ========================================================

    except HttpResponseError as e:

        error_message = safe_error_message(e)

        print(
            "\n[Azure] VM deployment failed."
        )

        print(
            f"Status: {e.status_code}"
        )

        print(
            f"Error: {error_message}"
        )

        failure_description = f"""
Azure VM deployment FAILED.

VM Name:
{vm_name}

Resource Group:
{resource_group_name}

Location:
{location}

Zone:
{zone or "Not specified"}

VNet:
{vnet_name}

Subnet:
{subnet_name}

VM Size:
{vm_size}

Azure Status Code:
{e.status_code}

Azure Error:
{error_message}

Status:
DEPLOYMENT FAILED

The VM was not confirmed as successfully created.
"""

        jira_update = None

        if jira_issue.get("success"):

            jira_update = update_jira_issue(
                issue_key=jira_issue["issue_key"],
                description=failure_description,
            )

        return {
            "success": False,

            "error":
                "AzureHttpResponseError",

            "status_code":
                e.status_code,

            "message":
                error_message,

            "jira": {
                "created":
                    jira_issue.get(
                        "success",
                        False,
                    ),

                "issue_key":
                    jira_issue.get(
                        "issue_key"
                    ),

                "issue_url":
                    jira_issue.get(
                        "issue_url"
                    ),

                "updated":
                    (
                        jira_update.get(
                            "success",
                            False,
                        )
                        if jira_update
                        else False
                    ),
            },
        }

    # ========================================================
    # GENERAL ERROR
    # ========================================================

    except Exception as e:

        error_message = safe_error_message(e)

        print(
            "\n[Azure] Unexpected VM error."
        )

        print(
            f"Type: {type(e).__name__}"
        )

        print(
            f"Error: {error_message}"
        )

        failure_description = f"""
Azure VM deployment FAILED.

VM Name:
{vm_name}

Resource Group:
{resource_group_name}

Location:
{location}

Zone:
{zone or "Not specified"}

VNet:
{vnet_name}

Subnet:
{subnet_name}

VM Size:
{vm_size}

Error Type:
{type(e).__name__}

Error:
{error_message}

Status:
DEPLOYMENT FAILED

The VM was not confirmed as successfully created.
"""

        jira_update = None

        if jira_issue.get("success"):

            jira_update = update_jira_issue(
                issue_key=jira_issue["issue_key"],
                description=failure_description,
            )

        return {
            "success": False,

            "error":
                type(e).__name__,

            "message":
                error_message,

            "jira": {
                "created":
                    jira_issue.get(
                        "success",
                        False,
                    ),

                "issue_key":
                    jira_issue.get(
                        "issue_key"
                    ),

                "issue_url":
                    jira_issue.get(
                        "issue_url"
                    ),

                "updated":
                    (
                        jira_update.get(
                            "success",
                            False,
                        )
                        if jira_update
                        else False
                    ),
            },
        }


# ============================================================
# FOUNDRY RESOURCE GROUP TOOL
# ============================================================

resource_group_tool = FunctionTool(

    name="create_resource_group",

    description="""
Create an Azure Resource Group.

Use only when the user explicitly asks to create
a resource group.

Required:
- resource_group_name
- location
""",

    parameters={
        "type": "object",

        "properties": {

            "resource_group_name": {
                "type": "string",
            },

            "location": {
                "type": "string",
            },
        },

        "required": [
            "resource_group_name",
            "location",
        ],

        "additionalProperties": False,
    },

    strict=True,
)


# ============================================================
# FOUNDRY VM TOOL
# ============================================================

vm_tool = FunctionTool(

    name="create_virtual_machine",

    description="""
Create an Azure Linux Virtual Machine.

The Resource Group must already exist.

The VNet and subnet must already exist.

Required:
- resource group
- VM name
- location
- zone
- VNet
- subnet
- VM size
- image
- admin username
- admin password
- public IP requirement

Do not invent missing values.

If required information is missing,
ask the user.

The application automatically:
1. Creates a Jira ticket.
2. Deploys the Azure VM.
3. Updates Jira after successful deployment.
4. Updates Jira if deployment fails.

Do NOT create a separate Jira ticket for the VM.
""",

    parameters={

        "type": "object",

        "properties": {

            "resource_group_name": {
                "type": "string",
            },

            "vm_name": {
                "type": "string",
            },

            "location": {
                "type": "string",
            },

            "zone": {
                "type": "string",
            },

            "vnet_name": {
                "type": "string",
            },

            "subnet_name": {
                "type": "string",
            },

            "vm_size": {
                "type": "string",
            },

            "image_publisher": {
                "type": "string",
            },

            "image_offer": {
                "type": "string",
            },

            "image_sku": {
                "type": "string",
            },

            "image_version": {
                "type": "string",
            },

            "admin_username": {
                "type": "string",
            },

            "admin_password": {
                "type": "string",
            },

            "create_public_ip": {
                "type": "boolean",
            },
        },

        "required": [
            "resource_group_name",
            "vm_name",
            "location",
            "zone",
            "vnet_name",
            "subnet_name",
            "vm_size",
            "image_publisher",
            "image_offer",
            "image_sku",
            "image_version",
            "admin_username",
            "admin_password",
            "create_public_ip",
        ],

        "additionalProperties": False,
    },

    strict=True,
)


# ============================================================
# MANUAL JIRA TOOL
# ============================================================

jira_tool = FunctionTool(

    name="create_jira_issue",

    description="""
Create a Jira issue manually.

Use this only for Jira issues unrelated to Azure VM
deployment.

For VM deployment, create_virtual_machine automatically
handles Jira creation and updates.
""",

    parameters={

        "type": "object",

        "properties": {

            "summary": {
                "type": "string",
            },

            "description": {
                "type": "string",
            },

            "issue_type": {
                "type": "string",
            },
        },

        "required": [
            "summary",
            "description",
            "issue_type",
        ],

        "additionalProperties": False,
    },

    strict=True,
)


# ============================================================
# CREATE FOUNDRY AGENT
# ============================================================

print(
    "\nCreating Foundry agent..."
)

agent = project_client.agents.create_version(

    agent_name=AGENT_NAME,

    definition=PromptAgentDefinition(

        model=DEPLOYMENT_NAME,

        instructions="""

You are an Azure infrastructure and Jira assistant.

You can perform:

1. Azure Resource Group creation.
2. Azure Linux VM creation.
3. Jira issue creation.


RESOURCE GROUP
---------------

Create a Resource Group only when explicitly requested.

Do not invent missing values.


VM DEPLOYMENT
-------------

Create a VM only when explicitly requested.

Collect:

- resource group
- VM name
- location
- zone
- VNet
- subnet
- VM size
- image
- admin username
- admin password
- public IP requirement

Never invent missing values.

Ask for missing information.


SUPPORTED IMAGES
----------------

Ubuntu 24.04 LTS:

publisher:
Canonical

offer:
ubuntu-24_04-lts

sku:
server

version:
latest


Ubuntu 22.04 LTS:

publisher:
Canonical

offer:
0001-com-ubuntu-server-jammy

sku:
22_04-lts-gen2

version:
latest


JIRA VM WORKFLOW
----------------

When create_virtual_machine is called:

1. Create Jira ticket.
2. Start Azure VM deployment.
3. If VM succeeds, update Jira with VM details.
4. If VM fails, update Jira with the failure.

Do not separately create Jira for VM deployment.

Never store the VM admin password in Jira.


SECURITY
--------

Never expose:

- Jira API token
- Azure credentials
- VM admin password

Never claim a VM was created unless the function
returns success.

Never claim a Jira issue was created unless the
function returns success.
""",

        tools=[
            resource_group_tool,
            vm_tool,
            jira_tool,
        ],
    ),
)

print(
    f"\nFoundry Agent Created: "
    f"{agent.name} "
    f"version={agent.version}"
)


# ============================================================
# OPENAI CLIENT
# ============================================================

openai_client = (
    project_client
    .get_openai_client()
)


# ============================================================
# CONVERSATION
# ============================================================

conversation = (
    openai_client
    .conversations
    .create()
)


# ============================================================
# FUNCTION EXECUTOR
# ============================================================

def execute_function(
    function_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:

    try:

        if function_name == "create_resource_group":

            return create_resource_group(
                resource_group_name=arguments[
                    "resource_group_name"
                ],
                location=arguments[
                    "location"
                ],
            )

        if function_name == "create_virtual_machine":

            return create_virtual_machine(
                resource_group_name=arguments[
                    "resource_group_name"
                ],
                vm_name=arguments[
                    "vm_name"
                ],
                location=arguments[
                    "location"
                ],
                zone=arguments[
                    "zone"
                ],
                vnet_name=arguments[
                    "vnet_name"
                ],
                subnet_name=arguments[
                    "subnet_name"
                ],
                vm_size=arguments[
                    "vm_size"
                ],
                image_publisher=arguments[
                    "image_publisher"
                ],
                image_offer=arguments[
                    "image_offer"
                ],
                image_sku=arguments[
                    "image_sku"
                ],
                image_version=arguments[
                    "image_version"
                ],
                admin_username=arguments[
                    "admin_username"
                ],
                admin_password=arguments[
                    "admin_password"
                ],
                create_public_ip=arguments[
                    "create_public_ip"
                ],
            )

        if function_name == "create_jira_issue":

            return create_jira_issue(
                summary=arguments[
                    "summary"
                ],
                description=arguments[
                    "description"
                ],
                issue_type=arguments[
                    "issue_type"
                ],
            )

        return {
            "success": False,
            "error": "UnknownFunction",
            "message": (
                f"Unknown function: {function_name}"
            ),
        }

    except Exception as e:

        return {
            "success": False,
            "error": type(e).__name__,
            "message": safe_error_message(e),
        }


# ============================================================
# CHAT
# ============================================================

def chat(
    user_prompt: str,
) -> str:

    try:

        response = (
            openai_client
            .responses
            .create(
                conversation=conversation.id,
                input=user_prompt,
                extra_body={
                    "agent_reference": {
                        "name": agent.name,
                        "type": "agent_reference",
                        "version": agent.version,
                    }
                },
            )
        )

        function_calls = [
            item
            for item in response.output
            if getattr(
                item,
                "type",
                None,
            ) == "function_call"
        ]

        if not function_calls:
            return response.output_text

        tool_outputs = []

        for item in function_calls:

            try:

                arguments = json.loads(
                    item.arguments
                )

            except json.JSONDecodeError as e:

                result = {
                    "success": False,
                    "error":
                        "InvalidFunctionArguments",
                    "message": str(e),
                }

            else:

                safe_arguments = dict(
                    arguments
                )

                if "admin_password" in safe_arguments:
                    safe_arguments[
                        "admin_password"
                    ] = "********"

                print(
                    f"\nFunction: {item.name}"
                )

                print(
                    json.dumps(
                        safe_arguments,
                        indent=2,
                    )
                )

                result = execute_function(
                    function_name=item.name,
                    arguments=arguments,
                )

            print(
                "\nFunction result:"
            )

            print(
                json.dumps(
                    result,
                    indent=2,
                )
            )

            tool_outputs.append(
                {
                    "type":
                        "function_call_output",

                    "call_id":
                        item.call_id,

                    "output":
                        json.dumps(result),
                }
            )

        final_response = (
            openai_client
            .responses
            .create(
                conversation=conversation.id,
                input=tool_outputs,
                extra_body={
                    "agent_reference": {
                        "name": agent.name,
                        "type": "agent_reference",
                        "version": agent.version,
                    }
                },
            )
        )

        return final_response.output_text

    except Exception as e:

        print(
            "\nCHAT ERROR:"
        )

        print(
            safe_error_message(e)
        )

        return (
            "The request could not be completed. "
            f"Error: {safe_error_message(e)}"
        )
