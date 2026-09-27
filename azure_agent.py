import os
import json
import base64
import requests
from typing import Any, Dict

from azure.identity import (
    DefaultAzureCredential,
    ManagedIdentityCredential,
)

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    FunctionTool,
)

from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import (
    NetworkInterface,
    NetworkInterfaceIPConfiguration,
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
    "",
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
# VALIDATE AZURE CONFIG
# ============================================================

if not SUBSCRIPTION_ID:
    print(
        "[WARNING] AZURE_SUBSCRIPTION_ID is not configured."
    )


# ============================================================
# AUTHENTICATION
# ============================================================

if os.getenv("WEBSITE_HOSTNAME"):
    print(
        "[Azure] Using Managed Identity."
    )

    credential = ManagedIdentityCredential()

else:
    print(
        "[Azure] Using DefaultAzureCredential."
    )

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
# SECURITY / ERROR HANDLING
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

def check_jira_configuration() -> Dict[str, Any]:

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
# CREATE JIRA TICKET
#
# IMPORTANT:
# This function is called ONLY after Azure deployment
# succeeds.
# ============================================================

def create_jira_issue(
    summary: str,
    description: str,
    issue_type: str = "Task",
) -> Dict[str, Any]:

    config = check_jira_configuration()

    if not config["configured"]:

        print(
            "[Jira] Configuration is incomplete."
        )

        return {
            "success": False,
            "error": "JiraConfigurationMissing",
            "message": (
                "Missing Jira configuration: "
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

        print(
            "[Jira] Creating ticket after successful Azure deployment..."
        )

        response = requests.post(
            url,
            headers=jira_headers(),
            json=payload,
            timeout=30,
        )

        if response.status_code not in (200, 201):

            print(
                f"[Jira] Creation failed: "
                f"{response.status_code}"
            )

            return {
                "success": False,
                "error": "JiraAPIError",
                "status_code": response.status_code,
                "message": response.text,
            }

        data = response.json()

        issue_key = data.get("key")
        issue_id = data.get("id")

        print(
            f"[Jira] Created issue: {issue_key}"
        )

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

        print(
            "[Jira] Exception while creating ticket:"
        )

        print(
            safe_error_message(e)
        )

        return {
            "success": False,
            "error": type(e).__name__,
            "message": safe_error_message(e),
        }


# ============================================================
# RESOURCE GROUP CREATION
#
# Flow:
#
# Azure RG creation
#       ↓
# Success?
#       ↓
# YES → Create ONE Jira ticket
#
# Failure?
#       ↓
# NO Jira ticket
# ============================================================

def create_resource_group(
    resource_group_name: str,
    location: str,
) -> Dict[str, Any]:

    if not resource_group_name:

        return {
            "success": False,
            "error": "MissingParameter",
            "message": (
                "Resource group name is required."
            ),
        }

    if not location:

        return {
            "success": False,
            "error": "MissingParameter",
            "message": (
                "Location is required."
            ),
        }

    try:

        print(
            f"[Azure] Creating resource group "
            f"'{resource_group_name}'..."
        )

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

        print(
            f"[Azure] Resource group created: "
            f"{result.name}"
        )

        # ====================================================
        # AZURE SUCCESS
        #
        # NOW create exactly ONE Jira ticket.
        # ====================================================

        jira_description = f"""
Azure Resource Group deployment completed successfully.

Resource Group:
{result.name}

Location:
{result.location}

Subscription:
{SUBSCRIPTION_ID}

Status:
DEPLOYMENT COMPLETED

This Jira ticket represents the customer's
resource group creation request.
"""

        jira_result = create_jira_issue(
            summary=(
                f"Azure Resource Group Created - "
                f"{result.name}"
            ),
            description=jira_description,
            issue_type="Task",
        )

        return {
            "success": True,

            "resource_group_name":
                result.name,

            "location":
                result.location,

            "message":
                (
                    f"Resource group "
                    f"'{result.name}' "
                    "created successfully."
                ),

            "jira": {
                "created":
                    jira_result.get(
                        "success",
                        False,
                    ),

                "issue_key":
                    jira_result.get(
                        "issue_key"
                    ),

                "issue_url":
                    jira_result.get(
                        "issue_url"
                    ),

                "message":
                    jira_result.get(
                        "message"
                    ),
            },
        }

    except HttpResponseError as e:

        error_message = safe_error_message(e)

        print(
            "[Azure] Resource group creation failed."
        )

        print(
            error_message
        )

        # IMPORTANT:
        # No Jira ticket is created because
        # Azure deployment failed.

        return {
            "success": False,
            "error": "AzureHttpResponseError",
            "status_code": e.status_code,
            "message": error_message,
            "jira": {
                "created": False,
            },
        }

    except Exception as e:

        error_message = safe_error_message(e)

        print(
            "[Azure] Unexpected resource group error."
        )

        print(
            error_message
        )

        return {
            "success": False,
            "error": type(e).__name__,
            "message": error_message,
            "jira": {
                "created": False,
            },
        }


# ============================================================
# VM CREATION
#
# One customer request may create:
#
# VM
# NIC
# Public IP
#
# But Jira = ONE ticket.
#
# Jira is created ONLY after the entire VM deployment
# succeeds.
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

    required = {
        "resource_group_name":
            resource_group_name,

        "vm_name":
            vm_name,

        "location":
            location,

        "vnet_name":
            vnet_name,

        "subnet_name":
            subnet_name,

        "vm_size":
            vm_size,

        "image_publisher":
            image_publisher,

        "image_offer":
            image_offer,

        "image_sku":
            image_sku,

        "image_version":
            image_version,

        "admin_username":
            admin_username,

        "admin_password":
            admin_password,
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

    try:

        # ====================================================
        # STEP 1
        # RESOURCE GROUP
        # ====================================================

        print(
            "[Azure] Checking resource group..."
        )

        resource_client.resource_groups.get(
            resource_group_name
        )

        # ====================================================
        # STEP 2
        # VNET
        # ====================================================

        print(
            "[Azure] Checking VNet..."
        )

        network_client.virtual_networks.get(
            resource_group_name,
            vnet_name,
        )

        # ====================================================
        # STEP 3
        # SUBNET
        # ====================================================

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
            f"[Azure] Subnet: {subnet.id}"
        )

        # ====================================================
        # STEP 4
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

                "public_ip_allocation_method":
                    "Static",

                "public_ip_address_version":
                    "IPv4",
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
                f"[Azure] Public IP created: "
                f"{public_ip.ip_address}"
            )

        # ====================================================
        # STEP 5
        # NIC
        # ====================================================

        print(
            "[Azure] Creating NIC..."
        )

        nic_name = (
            f"{vm_name}-nic"
        )

        ip_configuration = (
            NetworkInterfaceIPConfiguration(
                name=f"{vm_name}-ipconfig",

                private_ip_allocation_method=
                    "Dynamic",

                private_ip_address_version=
                    "IPv4",

                subnet={
                    "id": subnet.id,
                },
            )
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

        # ====================================================
        # STEP 6
        # IMAGE
        # ====================================================

        image_reference = ImageReference(
            publisher=image_publisher,
            offer=image_offer,
            sku=image_sku,
            version=image_version,
        )

        # ====================================================
        # STEP 7
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

        storage_profile = StorageProfile(
            image_reference=image_reference,
            os_disk=os_disk,
        )

        # ====================================================
        # STEP 8
        # HARDWARE
        # ====================================================

        hardware_profile = HardwareProfile(
            vm_size=vm_size
        )

        # ====================================================
        # STEP 9
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
        # STEP 10
        # NETWORK PROFILE
        # ====================================================

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
        # STEP 11
        # VM
        # ====================================================

        vm_parameters = VirtualMachine(
            location=location,

            hardware_profile=
                hardware_profile,

            storage_profile=
                storage_profile,

            os_profile=
                os_profile,

            network_profile=
                network_profile,
        )

        if zone:

            vm_parameters.zones = [
                str(zone)
            ]

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
        # STEP 12
        # GET PUBLIC IP
        # ====================================================

        public_ip_address = None

        if public_ip:

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
        # ENTIRE AZURE REQUEST SUCCEEDED
        #
        # NOW CREATE ONE JIRA TICKET.
        # ====================================================

        jira_description = f"""
Azure VM deployment completed successfully.

This ticket represents ONE customer request.

Resources created as part of this request:

VM:
{vm.name}

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

OS Image:
Publisher: {image_publisher}
Offer: {image_offer}
SKU: {image_sku}
Version: {image_version}

Deployment Status:
SUCCESS

The administrator password is intentionally
not stored in Jira.
"""

        jira_result = create_jira_issue(
            summary=(
                f"Azure VM Deployment Completed - "
                f"{vm.name}"
            ),
            description=jira_description,
            issue_type="Task",
        )

        # ====================================================
        # SUCCESS RESPONSE
        # ====================================================

        return {
            "success": True,

            "vm_name":
                vm.name,

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
                    jira_result.get(
                        "success",
                        False,
                    ),

                "issue_key":
                    jira_result.get(
                        "issue_key"
                    ),

                "issue_url":
                    jira_result.get(
                        "issue_url"
                    ),

                "message":
                    jira_result.get(
                        "message"
                    ),
            },

            "message": (
                f"VM '{vm.name}' "
                "and all requested resources "
                "were created successfully."
            ),
        }

    except HttpResponseError as e:

        error_message = safe_error_message(e)

        print(
            "[Azure] VM deployment failed."
        )

        print(
            f"Status: {e.status_code}"
        )

        print(
            error_message
        )

        # IMPORTANT:
        #
        # NO Jira ticket is created because
        # the complete customer request did not
        # successfully finish.

        return {
            "success": False,

            "error":
                "AzureHttpResponseError",

            "status_code":
                e.status_code,

            "message":
                error_message,

            "jira": {
                "created": False,
            },
        }

    except Exception as e:

        error_message = safe_error_message(e)

        print(
            "[Azure] Unexpected VM error."
        )

        print(
            f"Type: {type(e).__name__}"
        )

        print(
            error_message
        )

        # NO Jira ticket on failed deployment.

        return {
            "success": False,

            "error":
                type(e).__name__,

            "message":
                error_message,

            "jira": {
                "created": False,
            },
        }


# ============================================================
# FOUNDRY RESOURCE GROUP TOOL
# ============================================================

resource_group_tool = FunctionTool(
    name="create_resource_group",

    description="""
Create an Azure Resource Group.

Use only when the customer explicitly asks
to create a Resource Group.

The function creates exactly ONE Jira ticket
after the Azure Resource Group is successfully
created.

If Azure creation fails, no Jira ticket is created.

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

A single VM request may create:
- VM
- NIC
- Public IP

These are ONE customer request and therefore
must result in exactly ONE Jira ticket.

The Jira ticket is created ONLY after the
entire Azure deployment succeeds.

If any Azure deployment step fails, no Jira
ticket is created.

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
ask the customer.

Never create a separate Jira ticket for
the VM, NIC, or Public IP.
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

Use this ONLY when the customer explicitly
asks for a standalone Jira issue.

Do NOT use this tool for Azure resource
deployment requests.

Azure deployment functions automatically
create their own Jira ticket after successful
deployment.
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
3. Standalone Jira issue creation.


RESOURCE GROUP
==============

Create a Resource Group only when the customer
explicitly asks for one.

Never invent missing values.

The Resource Group function automatically
creates ONE Jira ticket after successful Azure
creation.

Do not call create_jira_issue separately after
a Resource Group deployment.


VM DEPLOYMENT
=============

Create a VM only when the customer explicitly
requests it.

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

Ask the customer for missing information.


SUPPORTED IMAGES
================

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


JIRA TICKET RULE
================

IMPORTANT:

Jira tickets represent CUSTOMER REQUESTS,
not individual Azure resources.

Example:

Customer asks:

"Create a VM with a NIC and Public IP."

Azure may create:

1. VM
2. NIC
3. Public IP

This is ONE customer request.

Therefore create EXACTLY ONE Jira ticket.

Never create:

- one VM Jira ticket
- one NIC Jira ticket
- one Public IP Jira ticket

Instead create ONE Jira ticket containing
all resources created for that request.


SUCCESS RULE
============

Create the Jira ticket ONLY after the Azure
operation requested by the customer succeeds.

If Azure deployment fails:

- do NOT create a Jira ticket
- report the Azure failure
- do not claim successful deployment


RESOURCE GROUP RULE
===================

Customer asks to create Resource Group.

If successful:

1. Azure creates Resource Group.
2. Function creates ONE Jira ticket.
3. Return Jira ticket information.

If unsuccessful:

1. Azure creation fails.
2. No Jira ticket.
3. Report failure.


VM RULE
=======

Customer asks to create VM.

The VM function may create:

- Public IP
- NIC
- VM

All are part of ONE request.

If the complete VM deployment succeeds:

1. Create ONE Jira ticket.
2. Include VM, NIC, Public IP and configuration
   details in that ticket.
3. Return Jira ticket information.

If deployment fails:

1. Do not create Jira ticket.
2. Report failure.


STANDALONE JIRA
===============

The create_jira_issue function is only for
standalone Jira requests that are unrelated
to Azure deployment.

Do not call it after Azure functions because
the Azure functions already handle Jira.


SECURITY
========

Never expose:

- Jira API token
- Azure credentials
- VM admin password

Never write the VM admin password into Jira.

Never claim an Azure resource was created unless
the corresponding function returns success.

Never claim a Jira ticket was created unless
the function returns Jira success.
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
                f"Unknown function: "
                f"{function_name}"
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
                    "message":
                        str(e),
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

        error_message = safe_error_message(e)

        print(
            "\nCHAT ERROR:"
        )

        print(
            error_message
        )

        return (
            "The request could not be completed. "
            f"Error: {error_message}"
        )
