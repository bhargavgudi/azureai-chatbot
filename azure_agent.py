import os
import json
import base64
import re
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

#from azure.mgmt.resource import ResourceManagementClient
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

# IMPORTANT:
# This MUST be the Azure Subscription ID GUID.
#
# Example:
# AZURE_SUBSCRIPTION_ID=12345678-1234-1234-1234-123456789abc
#
# Do NOT put:
# - subscription name
# - resource group name
# - "resourcegroups"
# - Azure Portal URL
# - /subscriptions/...
#
SUBSCRIPTION_ID = os.getenv(
    "AZURE_SUBSCRIPTION_ID",
    "",
).strip()


# ============================================================
# JIRA CONFIGURATION
# ============================================================

JIRA_BASE_URL = os.getenv(
    "JIRA_BASE_URL",
    "",
).strip().rstrip("/")

JIRA_EMAIL = os.getenv(
    "JIRA_EMAIL",
    "",
).strip()

JIRA_API_TOKEN = os.getenv(
    "JIRA_API_TOKEN",
    "",
).strip()

JIRA_PROJECT_KEY = os.getenv(
    "JIRA_PROJECT_KEY",
    "",
).strip()


# ============================================================
# SUBSCRIPTION VALIDATION
# ============================================================

SUBSCRIPTION_GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)


def validate_subscription_id() -> None:
    """
    Validate AZURE_SUBSCRIPTION_ID before Azure clients
    are created.

    Azure subscription IDs are GUIDs.
    """

    if not SUBSCRIPTION_ID:

        raise RuntimeError(
            "AZURE_SUBSCRIPTION_ID is not configured.\n"
            "Set it to the Azure subscription GUID."
        )

    if not SUBSCRIPTION_GUID_PATTERN.match(
        SUBSCRIPTION_ID
    ):

        raise RuntimeError(
            "Invalid AZURE_SUBSCRIPTION_ID.\n\n"
            f"Received: {SUBSCRIPTION_ID}\n\n"
            "Expected a subscription GUID like:\n"
            "12345678-1234-1234-1234-123456789abc\n\n"
            "Do not provide a subscription name, resource "
            "group name, URL, or '/subscriptions/...' path."
        )

    print(
        f"[Azure] Subscription ID configured: "
        f"{SUBSCRIPTION_ID}"
    )


validate_subscription_id()


# ============================================================
# AUTHENTICATION
# ============================================================

if os.getenv("WEBSITE_HOSTNAME"):

    print(
        "[Azure] Running in Azure App Service."
    )

    print(
        "[Azure] Using Managed Identity."
    )

    credential = ManagedIdentityCredential()

else:

    print(
        "[Azure] Running locally."
    )

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
# VERIFY AZURE SUBSCRIPTION
# ============================================================

def verify_azure_subscription() -> Dict[str, Any]:
    """
    Verify that the configured subscription ID can be accessed.

    This helps detect incorrect subscription configuration
    before attempting resource creation.
    """

    try:

        print(
            "\n[Azure] Verifying subscription access..."
        )

        # Listing resource groups forces Azure ARM to use:
        #
        # /subscriptions/<SUBSCRIPTION_ID>/resourcegroups
        #
        # This is a good early validation of the subscription
        # context.

        resource_groups = resource_client.resource_groups.list()

        # Only consume the first result.
        # We do not need to download the entire list.
        next(iter(resource_groups), None)

        print(
            "[Azure] Subscription verification successful."
        )

        print(
            f"[Azure] Subscription: {SUBSCRIPTION_ID}"
        )

        return {
            "success": True,
            "subscription_id": SUBSCRIPTION_ID,
            "message": "Azure subscription is accessible.",
        }

    except HttpResponseError as e:

        message = safe_error_message(e)

        print(
            "[Azure] Subscription verification failed."
        )

        print(message)

        return {
            "success": False,
            "subscription_id": SUBSCRIPTION_ID,
            "status_code": getattr(
                e,
                "status_code",
                None,
            ),
            "error": "AzureHttpResponseError",
            "message": message,
        }

    except Exception as e:

        message = safe_error_message(e)

        print(
            "[Azure] Unexpected subscription verification error."
        )

        print(message)

        return {
            "success": False,
            "subscription_id": SUBSCRIPTION_ID,
            "error": type(e).__name__,
            "message": message,
        }


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

def safe_error_message(
    error: Exception,
) -> str:

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
#
# Azure deployment functions call this function ONLY
# AFTER the entire customer request succeeds.
#
# Therefore:
#
# RG request:
#     Azure RG succeeds -> ONE Jira ticket
#
# VM request:
#     Public IP + NIC + VM succeed -> ONE Jira ticket
#
# Failed Azure request:
#     NO Jira ticket
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
            "\n[Jira] Creating ONE ticket for "
            "the completed customer request..."
        )

        response = requests.post(
            url,
            headers=jira_headers(),
            json=payload,
            timeout=30,
        )

        if response.status_code not in (
            200,
            201,
        ):

            print(
                "[Jira] Creation failed."
            )

            print(
                f"[Jira] HTTP status: "
                f"{response.status_code}"
            )

            print(
                f"[Jira] Response: "
                f"{response.text}"
            )

            return {
                "success": False,
                "error": "JiraAPIError",
                "status_code":
                    response.status_code,
                "message":
                    response.text,
            }

        data = response.json()

        issue_key = data.get("key")
        issue_id = data.get("id")

        print(
            f"[Jira] Created issue: "
            f"{issue_key}"
        )

        return {
            "success": True,

            "issue_key":
                issue_key,

            "issue_id":
                issue_id,

            "issue_url":
                f"{JIRA_BASE_URL}/browse/{issue_key}",

            "message":
                f"Jira issue {issue_key} created.",
        }

    except Exception as e:

        message = safe_error_message(e)

        print(
            "[Jira] Exception while creating ticket:"
        )

        print(message)

        return {
            "success": False,
            "error": type(e).__name__,
            "message": message,
        }


# ============================================================
# RESOURCE GROUP CREATION
#
# ONE CUSTOMER REQUEST
#        |
#        v
# Azure Resource Group
#        |
#        v
# SUCCESS
#        |
#        v
# ONE Jira ticket
#
# If Azure fails:
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
            "message":
                "Resource group name is required.",
        }

    if not location:

        return {
            "success": False,
            "error": "MissingParameter",
            "message":
                "Location is required.",
        }

    try:

        print(
            f"\n[Azure] Creating resource group "
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
        # AZURE REQUEST SUCCESS
        #
        # CREATE EXACTLY ONE JIRA TICKET.
        # ====================================================

        jira_description = f"""
Customer Azure deployment request completed successfully.

REQUEST TYPE:
Azure Resource Group Creation

RESOURCE GROUP:
{result.name}

LOCATION:
{result.location}

SUBSCRIPTION:
{SUBSCRIPTION_ID}

DEPLOYMENT STATUS:
SUCCESS

This Jira issue represents the complete customer request.

Only one Jira ticket was created for this request.
"""

        jira_result = create_jira_issue(
            summary=(
                f"Azure Resource Group Created - "
                f"{result.name}"
            ),

            description=jira_description,

            issue_type="Task",
        )

        response = {
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

        # Azure succeeded even if Jira failed.
        if not jira_result.get("success"):

            response["jira"]["warning"] = (
                "Azure deployment succeeded, "
                "but Jira ticket creation failed."
            )

        return response

    except HttpResponseError as e:

        error_message = safe_error_message(e)

        print(
            "[Azure] Resource group creation failed."
        )

        print(error_message)

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
                "reason":
                    "Azure deployment failed.",
            },
        }

    except Exception as e:

        error_message = safe_error_message(e)

        print(
            "[Azure] Unexpected resource group error."
        )

        print(error_message)

        return {
            "success": False,

            "error":
                type(e).__name__,

            "message":
                error_message,

            "jira": {
                "created": False,
                "reason":
                    "Azure deployment failed.",
            },
        }


# ============================================================
# VM CREATION
#
# ONE CUSTOMER REQUEST
#
# May create:
#
#     Public IP
#     NIC
#     VM
#
# But:
#
#     ONE customer request
#              |
#              v
#         ONE Jira ticket
#
# Jira is created ONLY after the VM deployment
# itself succeeds.
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
                "error":
                    "MissingParameter",
                "message":
                    (
                        f"Required parameter "
                        f"'{name}' is missing."
                    ),
            }

    try:

        # ====================================================
        # STEP 1 - RESOURCE GROUP
        # ====================================================

        print(
            "\n[Azure] Checking resource group..."
        )

        resource_client.resource_groups.get(
            resource_group_name
        )

        # ====================================================
        # STEP 2 - VNET
        # ====================================================

        print(
            "[Azure] Checking VNet..."
        )

        network_client.virtual_networks.get(
            resource_group_name,
            vnet_name,
        )

        # ====================================================
        # STEP 3 - SUBNET
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
            f"[Azure] Subnet found: "
            f"{subnet.id}"
        )

        # ====================================================
        # STEP 4 - PUBLIC IP
        # ====================================================

        public_ip = None

        if create_public_ip:

            public_ip_name = (
                f"{vm_name}-pip"
            )

            public_ip_parameters = {

                "location":
                    location,

                "sku": {
                    "name":
                        "Standard",
                },

                "public_ip_allocation_method":
                    "Static",

                "public_ip_address_version":
                    "IPv4",
            }

            if zone:

                public_ip_parameters[
                    "zones"
                ] = [
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
        # STEP 5 - NIC
        # ====================================================

        print(
            "[Azure] Creating NIC..."
        )

        nic_name = (
            f"{vm_name}-nic"
        )

        ip_configuration = (
            NetworkInterfaceIPConfiguration(
                name=
                    f"{vm_name}-ipconfig",

                private_ip_allocation_method=
                    "Dynamic",

                private_ip_address_version=
                    "IPv4",

                subnet={
                    "id":
                        subnet.id,
                },
            )
        )

        if public_ip:

            ip_configuration.public_ip_address = {
                "id":
                    public_ip.id,
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
            f"[Azure] NIC created: "
            f"{nic.name}"
        )

        # ====================================================
        # STEP 6 - IMAGE
        # ====================================================

        image_reference = ImageReference(
            publisher=
                image_publisher,

            offer=
                image_offer,

            sku=
                image_sku,

            version=
                image_version,
        )

        # ====================================================
        # STEP 7 - OS DISK
        # ====================================================

        managed_disk = ManagedDiskParameters(
            storage_account_type=
                "Premium_LRS"
        )

        os_disk = OSDisk(
            name=
                f"{vm_name}-osdisk",

            create_option=
                "FromImage",

            managed_disk=
                managed_disk,

            caching=
                "ReadWrite",
        )

        storage_profile = StorageProfile(
            image_reference=
                image_reference,

            os_disk=
                os_disk,
        )

        # ====================================================
        # STEP 8 - HARDWARE
        # ====================================================

        hardware_profile = HardwareProfile(
            vm_size=
                vm_size
        )

        # ====================================================
        # STEP 9 - OS PROFILE
        # ====================================================

        linux_configuration = LinuxConfiguration(
            disable_password_authentication=False
        )

        os_profile = OSProfile(
            computer_name=
                vm_name,

            admin_username=
                admin_username,

            admin_password=
                admin_password,

            linux_configuration=
                linux_configuration,
        )

        # ====================================================
        # STEP 10 - NETWORK PROFILE
        # ====================================================

        network_interface_reference = (
            NetworkInterfaceReference(
                id=
                    nic.id,

                primary=
                    True,
            )
        )

        network_profile = NetworkProfile(
            network_interfaces=[
                network_interface_reference
            ]
        )

        # ====================================================
        # STEP 11 - VM
        # ====================================================

        vm_parameters = VirtualMachine(
            location=
                location,

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
            f"[Azure] VM created: "
            f"{vm.name}"
        )

        # ====================================================
        # STEP 12 - GET PUBLIC IP
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
        # ENTIRE CUSTOMER REQUEST SUCCEEDED
        #
        # CREATE EXACTLY ONE JIRA TICKET.
        # ====================================================

        jira_description = f"""
Customer Azure deployment request completed successfully.

REQUEST TYPE:
Azure Virtual Machine Deployment

RESOURCES CREATED AS PART OF THIS REQUEST:

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

DEPLOYMENT STATUS:
SUCCESS

IMPORTANT:
The VM, NIC, Public IP and associated resources
are all part of ONE customer request.

Therefore this request generates exactly ONE
Jira ticket.

The administrator password is intentionally
NOT stored in Jira.
"""

        jira_result = create_jira_issue(
            summary=(
                f"Azure VM Deployment Completed - "
                f"{vm.name}"
            ),

            description=
                jira_description,

            issue_type=
                "Task",
        )

        response = {

            "success":
                True,

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

            "message":
                (
                    f"VM '{vm.name}' "
                    "and all requested resources "
                    "were created successfully."
                ),
        }

        if not jira_result.get("success"):

            response["jira"]["warning"] = (
                "Azure deployment succeeded, "
                "but Jira ticket creation failed."
            )

        return response

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

        return {

            "success":
                False,

            "error":
                "AzureHttpResponseError",

            "status_code":
                e.status_code,

            "message":
                error_message,

            "jira": {
                "created":
                    False,

                "reason":
                    "Azure deployment failed.",
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

        return {

            "success":
                False,

            "error":
                type(e).__name__,

            "message":
                error_message,

            "jira": {
                "created":
                    False,

                "reason":
                    "Azure deployment failed.",
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

After successful Azure creation, the Python
function automatically creates exactly ONE
Jira ticket for the complete customer request.

If Azure creation fails, no Jira ticket is created.

Required:
- resource_group_name
- location

Do not call create_jira_issue separately after
this function succeeds.
""",

    parameters={

        "type":
            "object",

        "properties": {

            "resource_group_name": {
                "type":
                    "string",
            },

            "location": {
                "type":
                    "string",
            },
        },

        "required": [
            "resource_group_name",
            "location",
        ],

        "additionalProperties":
            False,
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

One customer VM request may create:

- Public IP
- NIC
- VM

These are all part of ONE customer request.

Therefore exactly ONE Jira ticket must be created
after the COMPLETE VM deployment succeeds.

Never create separate Jira tickets for:
- VM
- NIC
- Public IP

If any Azure deployment step fails:
- do not create a Jira ticket
- report the Azure error

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
Ask the customer for missing values.
""",

    parameters={

        "type":
            "object",

        "properties": {

            "resource_group_name": {
                "type":
                    "string",
            },

            "vm_name": {
                "type":
                    "string",
            },

            "location": {
                "type":
                    "string",
            },

            "zone": {
                "type":
                    "string",
            },

            "vnet_name": {
                "type":
                    "string",
            },

            "subnet_name": {
                "type":
                    "string",
            },

            "vm_size": {
                "type":
                    "string",
            },

            "image_publisher": {
                "type":
                    "string",
            },

            "image_offer": {
                "type":
                    "string",
            },

            "image_sku": {
                "type":
                    "string",
            },

            "image_version": {
                "type":
                    "string",
            },

            "admin_username": {
                "type":
                    "string",
            },

            "admin_password": {
                "type":
                    "string",
            },

            "create_public_ip": {
                "type":
                    "boolean",
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

        "additionalProperties":
            False,
    },

    strict=True,
)


# ============================================================
# MANUAL JIRA TOOL
# ============================================================

jira_tool = FunctionTool(
    name="create_jira_issue",

    description="""
Create a standalone Jira issue.

Use this ONLY when the customer explicitly asks
for a Jira issue unrelated to Azure deployment.

Do NOT call this tool after:
- Resource Group creation
- VM creation
- NIC creation
- Public IP creation

Azure deployment functions automatically create
the single Jira ticket for the customer request.
""",

    parameters={

        "type":
            "object",

        "properties": {

            "summary": {
                "type":
                    "string",
            },

            "description": {
                "type":
                    "string",
            },

            "issue_type": {
                "type":
                    "string",
            },
        },

        "required": [
            "summary",
            "description",
            "issue_type",
        ],

        "additionalProperties":
            False,
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

    agent_name=
        AGENT_NAME,

    definition=
        PromptAgentDefinition(

            model=
                DEPLOYMENT_NAME,

            instructions="""
You are an Azure infrastructure and Jira assistant.

============================================================
AZURE SUBSCRIPTION
============================================================

All Azure resources must be created in the configured
Azure subscription.

Do not invent or modify subscription IDs.

============================================================
RESOURCE GROUP
============================================================

Create a Resource Group only when the customer explicitly
asks for one.

Required:
- resource group name
- Azure location

Never invent missing values.

After successful Resource Group creation, the Python function
automatically creates EXACTLY ONE Jira ticket.

Do NOT call create_jira_issue separately.

============================================================
VM DEPLOYMENT
============================================================

Create a VM only when the customer explicitly requests it.

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

============================================================
SUPPORTED IMAGES
============================================================

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

============================================================
JIRA RULE
============================================================

Jira tickets represent CUSTOMER REQUESTS.

They do NOT represent individual Azure resources.

Example:

Customer asks:

"Create a VM with a NIC and Public IP."

Azure creates:

1. Public IP
2. NIC
3. VM

These resources are part of ONE customer request.

Therefore:

ONE CUSTOMER REQUEST
=
ONE JIRA TICKET

Never create:

- VM Jira ticket
- NIC Jira ticket
- Public IP Jira ticket

Instead create one Jira ticket containing all resources
created as part of that request.

============================================================
RESOURCE GROUP EXAMPLE
============================================================

Customer:

"Create resource group demo-rg in eastus."

If Azure succeeds:

1. Resource Group is created.
2. Python function creates ONE Jira ticket.
3. Return Azure success and Jira ticket information.

If Azure fails:

1. Do not create Jira ticket.
2. Report Azure failure.

============================================================
VM EXAMPLE
============================================================

Customer:

"Create VM demo-vm."

The function may create:

- Public IP
- NIC
- VM

If the complete VM deployment succeeds:

1. Create ONE Jira ticket.
2. Include VM details.
3. Include NIC details.
4. Include Public IP details.
5. Include deployment configuration.
6. Return the Jira ticket.

Do not create multiple Jira tickets.

============================================================
FAILURE RULE
============================================================

If Azure deployment fails:

DO NOT create Jira ticket.

Report the Azure error.

Never claim deployment succeeded unless the Azure function
returns success=True.

============================================================
JIRA FAILURE
============================================================

If Azure deployment succeeds but Jira creation fails:

Report:

- Azure deployment succeeded.
- Jira creation failed.

Do not claim that the Jira ticket was created.

============================================================
STANDALONE JIRA
============================================================

The create_jira_issue tool can be used only for a standalone
Jira request unrelated to Azure deployment.

Do not use it after Azure deployment functions because those
functions already create the single Jira ticket.

============================================================
SECURITY
============================================================

Never expose:

- Jira API token
- Azure credentials
- VM administrator password

Never write the VM administrator password into Jira.

Never claim a Jira issue exists unless the Jira function
returned success=True.
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

                resource_group_name=
                    arguments[
                        "resource_group_name"
                    ],

                location=
                    arguments[
                        "location"
                    ],
            )

        if function_name == "create_virtual_machine":

            return create_virtual_machine(

                resource_group_name=
                    arguments[
                        "resource_group_name"
                    ],

                vm_name=
                    arguments[
                        "vm_name"
                    ],

                location=
                    arguments[
                        "location"
                    ],

                zone=
                    arguments[
                        "zone"
                    ],

                vnet_name=
                    arguments[
                        "vnet_name"
                    ],

                subnet_name=
                    arguments[
                        "subnet_name"
                    ],

                vm_size=
                    arguments[
                        "vm_size"
                    ],

                image_publisher=
                    arguments[
                        "image_publisher"
                    ],

                image_offer=
                    arguments[
                        "image_offer"
                    ],

                image_sku=
                    arguments[
                        "image_sku"
                    ],

                image_version=
                    arguments[
                        "image_version"
                    ],

                admin_username=
                    arguments[
                        "admin_username"
                    ],

                admin_password=
                    arguments[
                        "admin_password"
                    ],

                create_public_ip=
                    arguments[
                        "create_public_ip"
                    ],
            )

        if function_name == "create_jira_issue":

            return create_jira_issue(

                summary=
                    arguments[
                        "summary"
                    ],

                description=
                    arguments[
                        "description"
                    ],

                issue_type=
                    arguments[
                        "issue_type"
                    ],
            )

        return {

            "success":
                False,

            "error":
                "UnknownFunction",

            "message":
                (
                    f"Unknown function: "
                    f"{function_name}"
                ),
        }

    except Exception as e:

        return {

            "success":
                False,

            "error":
                type(e).__name__,

            "message":
                safe_error_message(e),
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

                conversation=
                    conversation.id,

                input=
                    user_prompt,

                extra_body={
                    "agent_reference": {

                        "name":
                            agent.name,

                        "type":
                            "agent_reference",

                        "version":
                            agent.version,
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

                    "success":
                        False,

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

                    function_name=
                        item.name,

                    arguments=
                        arguments,
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

            tool_outputs.append({

                "type":
                    "function_call_output",

                "call_id":
                    item.call_id,

                "output":
                    json.dumps(
                        result
                    ),
            })

        final_response = (
            openai_client
            .responses
            .create(

                conversation=
                    conversation.id,

                input=
                    tool_outputs,

                extra_body={
                    "agent_reference": {

                        "name":
                            agent.name,

                        "type":
                            "agent_reference",

                        "version":
                            agent.version,
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


# ============================================================
# STARTUP SUBSCRIPTION TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\n============================================================"
    )

    print(
        "Azure AI Resource Creator"
    )

    print(
        "============================================================"
    )

    subscription_test = (
        verify_azure_subscription()
    )

    if not subscription_test["success"]:

        print(
            "\n[ERROR] Azure subscription verification failed."
        )

        print(
            subscription_test["message"]
        )

        print(
            "\nCheck AZURE_SUBSCRIPTION_ID and the identity's "
            "permissions."
        )

        raise SystemExit(1)

    print(
        "\nReady for customer requests."
    )

    print(
        "Type 'exit' to quit."
    )

    while True:

        try:

            user_prompt = input(
                "\nCustomer: "
            )

        except KeyboardInterrupt:

            print(
                "\nExiting..."
            )

            break

        if not user_prompt.strip():

            continue

        if user_prompt.lower().strip() in (
            "exit",
            "quit",
        ):

            print(
                "Goodbye."
            )

            break

        answer = chat(
            user_prompt
        )

        print(
            f"\nAssistant: {answer}"
        )
