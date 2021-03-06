import inspect
from logging import Logger
from typing import Optional, Callable, Dict, Any

from slack_sdk.errors import SlackApiError
from slack_sdk.oauth import InstallationStore
from slack_sdk.oauth.installation_store import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation

from slack_bolt.authorization.authorize_args import AuthorizeArgs
from slack_bolt.authorization.authorize_result import AuthorizeResult
from slack_bolt.context.context import BoltContext


class Authorize:
    def __init__(self):
        pass

    def __call__(
        self,
        *,
        context: BoltContext,
        enterprise_id: Optional[str],
        team_id: str,
        user_id: Optional[str],
    ) -> Optional[AuthorizeResult]:
        raise NotImplementedError()


class CallableAuthorize(Authorize):
    def __init__(
        self, *, logger: Logger, func: Callable[..., AuthorizeResult],
    ):
        self.logger = logger
        self.func = func
        self.arg_names = inspect.getfullargspec(func).args

    def __call__(
        self,
        *,
        context: BoltContext,
        enterprise_id: Optional[str],
        team_id: str,
        user_id: Optional[str],
    ) -> Optional[AuthorizeResult]:
        try:
            all_available_args = {
                "args": AuthorizeArgs(
                    context=context,
                    enterprise_id=enterprise_id,
                    team_id=team_id,
                    user_id=user_id,
                ),
                "logger": context.logger,
                "client": context.client,
                "context": context,
                "enterprise_id": enterprise_id,
                "team_id": team_id,
                "user_id": user_id,
            }
            for k, v in context.items():
                if k not in all_available_args:
                    all_available_args[k] = v

            kwargs: Dict[str, Any] = {  # type: ignore
                k: v for k, v in all_available_args.items() if k in self.arg_names  # type: ignore
            }
            found_arg_names = kwargs.keys()
            for name in self.arg_names:
                if name not in found_arg_names:
                    self.logger.warning(f"{name} is not a valid argument")
                    kwargs[name] = None

            auth_result = self.func(**kwargs)
            if auth_result is None:
                return auth_result

            if isinstance(auth_result, AuthorizeResult):
                return auth_result
            else:
                raise ValueError(
                    f"Unexpected returned value from authorize function (type: {type(auth_result)})"
                )
        except SlackApiError as err:
            self.logger.debug(
                f"The stored bot token for enterprise_id: {enterprise_id} team_id: {team_id} "
                f"is no longer valid. (response: {err.response})"
            )
            return None


class InstallationStoreAuthorize(Authorize):
    authorize_result_cache: Dict[str, AuthorizeResult]
    bot_only: bool
    find_installation_available: bool

    def __init__(
        self,
        *,
        logger: Logger,
        installation_store: InstallationStore,
        # For v1.0.x compatibility and people who still want its simplicity
        # use only InstallationStore#find_bot(enterprise_id, team_id)
        bot_only: bool = False,
        cache_enabled: bool = False,
    ):
        self.logger = logger
        self.installation_store = installation_store
        self.bot_only = bot_only
        self.cache_enabled = cache_enabled
        self.authorize_result_cache = {}
        self.find_installation_available = hasattr(
            installation_store, "find_installation"
        )

    def __call__(
        self,
        *,
        context: BoltContext,
        enterprise_id: Optional[str],
        team_id: str,
        user_id: Optional[str],
    ) -> Optional[AuthorizeResult]:

        bot_token: Optional[str] = None
        user_token: Optional[str] = None

        if not self.bot_only and self.find_installation_available:
            # since v1.1, this is the default way
            try:
                installation: Optional[
                    Installation
                ] = self.installation_store.find_installation(
                    enterprise_id=enterprise_id,
                    team_id=team_id,
                    is_enterprise_install=context.is_enterprise_install,
                )
                if installation is None:
                    self._debug_log_for_not_found(enterprise_id, team_id)
                    return None

                if installation.user_id != user_id:
                    # try to fetch the request user's installation
                    # to reflect the user's access token if exists
                    user_installation = self.installation_store.find_installation(
                        enterprise_id=enterprise_id,
                        team_id=team_id,
                        user_id=user_id,
                        is_enterprise_install=context.is_enterprise_install,
                    )
                    if user_installation is not None:
                        installation = user_installation

                bot_token, user_token = installation.bot_token, installation.user_token
            except NotImplementedError as _:
                self.find_installation_available = False

        if self.bot_only or not self.find_installation_available:
            # Use find_bot to get bot value (legacy)
            bot: Optional[Bot] = self.installation_store.find_bot(
                enterprise_id=enterprise_id,
                team_id=team_id,
                is_enterprise_install=context.is_enterprise_install,
            )
            if bot is None:
                self._debug_log_for_not_found(enterprise_id, team_id)
                return None
            bot_token, user_token = bot.bot_token, None

        token: Optional[str] = bot_token or user_token
        if token is None:
            return None

        # Check cache to see if the bot object already exists
        if self.cache_enabled and token in self.authorize_result_cache:
            return self.authorize_result_cache[token]

        try:
            auth_test_api_response = context.client.auth_test(token=token)
            authorize_result = AuthorizeResult.from_auth_test_response(
                auth_test_response=auth_test_api_response,
                bot_token=bot_token,
                user_token=user_token,
            )
            if self.cache_enabled:
                self.authorize_result_cache[token] = authorize_result
            return authorize_result
        except SlackApiError as err:
            self.logger.debug(
                f"The stored bot token for enterprise_id: {enterprise_id} team_id: {team_id} "
                f"is no longer valid. (response: {err.response})"
            )
            return None

    # ------------------------------------------------

    def _debug_log_for_not_found(
        self, enterprise_id: Optional[str], team_id: Optional[str]
    ):
        self.logger.debug(
            "No installation data found "
            f"for enterprise_id: {enterprise_id} team_id: {team_id}"
        )
