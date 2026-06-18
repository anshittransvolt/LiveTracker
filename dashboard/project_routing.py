from urllib.parse import urlsplit, urlunsplit

from .vendor_spv_list import VENDOR_SPV_LIST


PROJECT_SCOPED_NAMESPACES = {
    "alarms",
    "battery",
    "livenotif",
    "livetracker",
    "mis",
    "reports",
    "roster",
    "vehicle",
}

DASHBOARD_PROJECT_SEGMENTS = {
    "dashboard",
    "profile",
    "revision-history",
    "feedbacklist",
    "administration",
    "vehicles",
    "api",
}

GLOBAL_DASHBOARD_URL_NAMES = {
    "root",
    "login",
    "logout",
    "set_project",
    "tos",
    "privacy",
    "forgot_password_request",
    "forgot_password_verify",
    "change_password_request",
    "change_password_verify",
    "ms_login",
    "ms_callback",
    "set_active_project",
    "api_user_projects",
}

PROJECT_SCOPED_TOP_LEVEL_SEGMENTS = PROJECT_SCOPED_NAMESPACES | DASHBOARD_PROJECT_SEGMENTS
DASHBOARD_GLOBAL_SEGMENTS = {
    "login",
    "logout",
    "set-project",
    "tos",
    "privacy",
    "forgot-password",
    "change-password",
    "microsoft",
}


PROJECT_CODE_BY_SLUG = {
    project.lower().replace("_", "-"): project for project in VENDOR_SPV_LIST
}


def get_default_project_code():
    if "ULTRATECH" in VENDOR_SPV_LIST:
        return "ULTRATECH"

    return next(iter(VENDOR_SPV_LIST))


def normalize_project_code(value):
    if not value:
        return None

    normalized = str(value).strip()
    if not normalized:
        return None

    upper_value = normalized.upper().replace("-", "_")
    if upper_value in VENDOR_SPV_LIST:
        return upper_value

    return PROJECT_CODE_BY_SLUG.get(normalized.lower())


def project_to_slug(project_code):
    canonical = normalize_project_code(project_code)
    if not canonical:
        return None

    return canonical.lower().replace("_", "-")


def strip_project_prefix(path):
    if not path:
        return "/"

    split_result = urlsplit(path)
    raw_path = split_result.path or "/"
    segments = [segment for segment in raw_path.split("/") if segment]

    if segments and normalize_project_code(segments[0]):
        stripped_segments = segments[1:]
        stripped_path = "/" + "/".join(stripped_segments) if stripped_segments else "/"
    else:
        stripped_path = raw_path

    return urlunsplit(
        (
            split_result.scheme,
            split_result.netloc,
            stripped_path,
            split_result.query,
            split_result.fragment,
        )
    )


def is_project_scoped_match(resolver_match):
    if resolver_match is None:
        return False

    namespace = resolver_match.namespace
    url_name = resolver_match.url_name

    if namespace in PROJECT_SCOPED_NAMESPACES:
        return True

    if namespace == "dashboard":
        return url_name not in GLOBAL_DASHBOARD_URL_NAMES

    return False


def is_project_scoped_path(path):
    raw_path = urlsplit(path).path or "/"
    stripped_path = urlsplit(strip_project_prefix(raw_path)).path or "/"
    segments = [segment for segment in stripped_path.split("/") if segment]

    if not segments:
        return False

    first_segment = segments[0]
    if first_segment not in PROJECT_SCOPED_TOP_LEVEL_SEGMENTS:
        return False

    if first_segment == "dashboard" and len(segments) > 1 and segments[1] in DASHBOARD_GLOBAL_SEGMENTS:
        return False

    return True


def build_project_prefixed_path(path, project_code):
    canonical_project = normalize_project_code(project_code) or get_default_project_code()
    project_slug = project_to_slug(canonical_project)

    split_result = urlsplit(path)
    raw_path = split_result.path or "/"
    segments = [segment for segment in raw_path.split("/") if segment]

    if not segments:
        new_path = f"/{project_slug}/dashboard/"
    elif normalize_project_code(segments[0]):
        segments[0] = project_slug
        new_path = "/" + "/".join(segments)
    elif is_project_scoped_path(raw_path):
        new_path = f"/{project_slug}{raw_path if raw_path.startswith('/') else '/' + raw_path}"
    else:
        new_path = f"/{project_slug}/dashboard/"

    if raw_path.endswith("/") and not new_path.endswith("/"):
        new_path += "/"

    return urlunsplit(
        (
            split_result.scheme,
            split_result.netloc,
            new_path,
            split_result.query,
            split_result.fragment,
        )
    )
