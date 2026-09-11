"""Budget stop used by request ledgers; independent of authentication storage."""
from ..errors import ProviderError


class RequestBudgetExceeded(ProviderError):
    pass

