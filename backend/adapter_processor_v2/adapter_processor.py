import json
import logging
from typing import Any

from account_v2.models import User
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from platform_settings_v2.platform_auth_service import PlatformAuthenticationService
from tenant_account_v2.organization_member_service import OrganizationMemberService

from adapter_processor_v2.constants import AdapterKeys, AllowedDomains
from adapter_processor_v2.exceptions import (
    InternalServiceError,
    InValidAdapterId,
    TestAdapterError,
)
from unstract.sdk.adapters.adapterkit import Adapterkit
from unstract.sdk.adapters.base import Adapter
from unstract.sdk.adapters.enums import AdapterTypes
from unstract.sdk.adapters.x2text.constants import X2TextConstants
from unstract.sdk.exceptions import SdkError

from .models import AdapterInstance, UserDefaultAdapter

logger = logging.getLogger(__name__)

try:
    from plugins.subscription.time_trials.subscription_adapter import add_unstract_key
except ImportError:
    add_unstract_key = None


class AdapterProcessor:
    @staticmethod
    def get_json_schema(adapter_id: str) -> dict[str, Any]:
        """Function to return JSON Schema for Adapters."""
        schema_details: dict[str, Any] = {}
        updated_adapters = AdapterProcessor.__fetch_adapters_by_key_value(
            AdapterKeys.ID, adapter_id
        )
        if len(updated_adapters) != 0:
            schema_details[AdapterKeys.JSON_SCHEMA] = json.loads(
                updated_adapters[0].get(AdapterKeys.JSON_SCHEMA)
            )
        else:
            logger.error(f"Invalid adapter Id : {adapter_id} while fetching JSON Schema")
            raise InValidAdapterId()
        return schema_details

    @staticmethod
    def get_all_supported_adapters(user_email: str, type: str) -> list[dict[Any, Any]]:
        """Function to return list of all supported adapters."""
        supported_adapters = []
        updated_adapters = []
        updated_adapters = AdapterProcessor.__fetch_adapters_by_key_value(
            AdapterKeys.ADAPTER_TYPE, type
        )
        is_special_user = any(
            identifier in user_email for identifier in AllowedDomains.list()
        )

        for each_adapter in updated_adapters:
            adapter_id = each_adapter.get(AdapterKeys.ID)
            if not is_special_user and adapter_id.startswith("noOp"):
                continue

            supported_adapters.append(
                {
                    AdapterKeys.ID: adapter_id,
                    AdapterKeys.NAME: each_adapter.get(AdapterKeys.NAME),
                    AdapterKeys.DESCRIPTION: each_adapter.get(AdapterKeys.DESCRIPTION),
                    AdapterKeys.ICON: each_adapter.get(AdapterKeys.ICON),
                    AdapterKeys.ADAPTER_TYPE: each_adapter.get(AdapterKeys.ADAPTER_TYPE),
                }
            )
        return supported_adapters

    @staticmethod
    def get_adapter_data_with_key(adapter_id: str, key_value: str) -> Any:
        """Generic Function to get adapter data with provided key."""
        updated_adapters = AdapterProcessor.__fetch_adapters_by_key_value(
            "id", adapter_id
        )
        if len(updated_adapters) == 0:
            logger.error(f"Invalid adapter ID {adapter_id} while invoking utility")
            raise InValidAdapterId()
        return updated_adapters[0].get(key_value)

    @staticmethod
    def test_adapter(adapter_id: str, adapter_metadata: dict[str, Any]) -> bool:
        logger.info(f"Testing adapter: {adapter_id}")
        try:
            adapter_class = Adapterkit().get_adapter_class_by_adapter_id(adapter_id)

            if adapter_metadata.pop(AdapterKeys.ADAPTER_TYPE) == AdapterKeys.X2TEXT:
                if (
                    adapter_metadata.get(AdapterKeys.PLATFORM_PROVIDED_UNSTRACT_KEY)
                    and add_unstract_key
                ):
                    adapter_metadata = add_unstract_key(adapter_metadata)
                adapter_metadata[X2TextConstants.X2TEXT_HOST] = settings.X2TEXT_HOST
                adapter_metadata[X2TextConstants.X2TEXT_PORT] = settings.X2TEXT_PORT
                platform_key = PlatformAuthenticationService.get_active_platform_key()
                adapter_metadata[X2TextConstants.PLATFORM_SERVICE_API_KEY] = str(
                    platform_key.key
                )

            adapter_instance = adapter_class(adapter_metadata)
            test_result: bool = adapter_instance.test_connection()
            return test_result
        except SdkError as e:
            raise TestAdapterError(
                e, adapter_name=adapter_metadata[AdapterKeys.ADAPTER_NAME]
            )

    @staticmethod
    def update_adapter_metadata(adapter_metadata_b: Any, **kwargs) -> Any:
        if add_unstract_key:
            encryption_secret: str = settings.ENCRYPTION_KEY
            f: Fernet = Fernet(encryption_secret.encode("utf-8"))

            adapter_metadata = json.loads(
                f.decrypt(bytes(adapter_metadata_b).decode("utf-8"))
            )
            adapter_metadata = add_unstract_key(adapter_metadata, **kwargs)

            adapter_metadata_b = f.encrypt(json.dumps(adapter_metadata).encode("utf-8"))
            return adapter_metadata_b
        return adapter_metadata_b

    @staticmethod
    def __fetch_adapters_by_key_value(key: str, value: Any) -> Adapter:
        """Fetches a list of adapters that have an attribute matching key and
        value.
        """
        logger.info(f"Fetching adapter list for {key} with {value}")
        adapter_kit = Adapterkit()
        adapters = adapter_kit.get_adapters_list()
        return [iterate for iterate in adapters if iterate[key] == value]

    @staticmethod
    def set_default_triad(default_triad: dict[str, str], user: User) -> None:
        try:
            organization_member = OrganizationMemberService.get_user_by_id(user.id)
            (
                user_default_adapter,
                created,
            ) = UserDefaultAdapter.objects.get_or_create(
                organization_member=organization_member
            )

            if default_triad.get(AdapterKeys.LLM_DEFAULT, None):
                user_default_adapter.default_llm_adapter = AdapterInstance.objects.get(
                    pk=default_triad[AdapterKeys.LLM_DEFAULT]
                )
            if default_triad.get(AdapterKeys.EMBEDDING_DEFAULT, None):
                user_default_adapter.default_embedding_adapter = (
                    AdapterInstance.objects.get(
                        pk=default_triad[AdapterKeys.EMBEDDING_DEFAULT]
                    )
                )

            if default_triad.get(AdapterKeys.VECTOR_DB_DEFAULT, None):
                user_default_adapter.default_vector_db_adapter = (
                    AdapterInstance.objects.get(
                        pk=default_triad[AdapterKeys.VECTOR_DB_DEFAULT]
                    )
                )

            if default_triad.get(AdapterKeys.X2TEXT_DEFAULT, None):
                user_default_adapter.default_x2text_adapter = AdapterInstance.objects.get(
                    pk=default_triad[AdapterKeys.X2TEXT_DEFAULT]
                )

            user_default_adapter.save()

            logger.info("Changed defaults successfully")
        except Exception as e:
            logger.error(f"Unable to save defaults because: {e}")
            if isinstance(e, InValidAdapterId):
                raise e
            else:
                raise InternalServiceError()

    @staticmethod
    def get_adapter_instance_by_id(adapter_instance_id: str) -> Adapter:
        """Get the adapter instance by its ID.

        Parameters:
        - adapter_instance_id (str): The ID of the adapter instance.

        Returns:
        - Adapter: The adapter instance with the specified ID.

        Raises:
        - Exception: If there is an error while fetching the adapter instance.
        """
        try:
            adapter = AdapterInstance.objects.get(id=adapter_instance_id)
        except Exception as e:
            logger.error(f"Unable to fetch adapter: {e}")
        if not adapter:
            logger.error("Unable to fetch adapter")
        return adapter.adapter_name

    @staticmethod
    def get_adapters_by_type(
        adapter_type: AdapterTypes, user: User
    ) -> list[AdapterInstance]:
        """Get a list of adapters by their type.

        Parameters:
        - adapter_type (AdapterTypes): The type of adapters to retrieve.
        - user: Logged in User

        Returns:
        - list[AdapterInstance]: A list of AdapterInstance objects that match
            the specified adapter type.
        """
        adapters: list[AdapterInstance] = AdapterInstance.objects.for_user(user).filter(
            adapter_type=adapter_type.value,
        )
        return adapters

    @staticmethod
    def get_adapter_by_name_and_type(
        adapter_type: AdapterTypes,
        adapter_name: str | None = None,
    ) -> AdapterInstance | None:
        """Get the adapter instance by its name and type.

        Parameters:
        - adapter_name (str): The name of the adapter instance.
        - adapter_type (AdapterTypes): The type of the adapter instance.

        Returns:
        - AdapterInstance: The adapter with the specified name and type.
        """
        if adapter_name:
            adapter: AdapterInstance = AdapterInstance.objects.get(
                adapter_name=adapter_name, adapter_type=adapter_type.value
            )
        else:
            try:
                adapter = AdapterInstance.objects.get(
                    adapter_type=adapter_type.value, is_default=True
                )
            except AdapterInstance.DoesNotExist:
                return None
        return adapter

    @staticmethod
    def get_default_adapters(user: User) -> list[AdapterInstance]:
        """Retrieve a list of default adapter instances. This method queries
        the database to fetch all adapter instances marked as default.

        Raises:
            InternalServiceError: If an unexpected error occurs during
            the database query.

        Returns:
            list[AdapterInstance]: A list of AdapterInstance objects that are
            marked as default.
        """
        try:
            adapters: list[AdapterInstance] = []

            organization_member = OrganizationMemberService.get_user_by_id(id=user.id)
            default_adapter: UserDefaultAdapter = UserDefaultAdapter.objects.get(
                organization_member=organization_member
            )

            if default_adapter.default_embedding_adapter:
                adapters.append(default_adapter.default_embedding_adapter)
            if default_adapter.default_llm_adapter:
                adapters.append(default_adapter.default_llm_adapter)
            if default_adapter.default_vector_db_adapter:
                adapters.append(default_adapter.default_vector_db_adapter)
            if default_adapter.default_x2text_adapter:
                adapters.append(default_adapter.default_x2text_adapter)

            return adapters
        except ObjectDoesNotExist as e:
            logger.error(f"No default adapters found: {e}")
            raise InternalServiceError(
                "No default adapters found, configure them through Platform Settings"
            )
