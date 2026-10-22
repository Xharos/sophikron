"""Safe domain errors translated by the HTTP boundary without private diagnostics."""


class AuthError(Exception):
    """Carry an HTTP-compatible status and a public, nontechnical explanation."""

    def __init__(self, status: int, message: str, retry_after: int | None = None) -> None:
        """Initialize a sanitized error without storing credentials or account identifiers."""
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


LOGIN_FAILED = "Identifiant ou mot de passe incorrect."
LOGIN_REQUIRED = "Veuillez vous connecter."
FORBIDDEN = "Vous n’êtes pas autorisé à effectuer cette action."
INVALID_INVITATION = "Ce lien n’est pas valide. Demandez une nouvelle invitation."
INVALID_REQUEST = "La demande n’a pas pu être acceptée."
