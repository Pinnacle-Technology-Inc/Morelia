"""Host folder browsing for the session wizard's sink-location picker.

A browser file dialog can only ever see the machine the *browser* runs on, and
it never reveals the chosen directory — only a filename. A sink file is opened
by this daemon, so the picker browses this machine's disk through the API
instead, and returns whole absolute paths that ``sink_location`` accepts as-is
(app/services/sink_paths.resolve_sink_location passes absolute paths through
byte-for-byte).

There is no path sandbox here on purpose: the dashboard is a localhost-only
control plane, and the bind address is the trust boundary. If this API ever
binds to anything but loopback, this endpoint becomes host-wide directory
enumeration for anyone who can reach the port, and needs a guard first.
"""

from flask_smorest import Blueprint, abort

from app.api.schemas import (
    DirectoryListingSchema,
    DirectoryQuerySchema,
    NewDirectorySchema,
    RootListingSchema,
)
from app.services.sink_paths import (
    InvalidFolderName,
    create_directory,
    host_roots,
    list_directories,
)

blp = Blueprint(
    "filesystem",
    __name__,
    url_prefix="/api/v1/filesystem",
    description="Browse this host's folders when choosing a sink output location.",
)


@blp.route("/roots", methods=["GET"])
@blp.response(200, RootListingSchema)
def list_roots():
    """Drives (Windows) or "/" (POSIX) — where the picker starts when going above a root."""
    return {"roots": host_roots()}


@blp.route("/directories", methods=["GET"])
@blp.arguments(DirectoryQuerySchema, location="query")
@blp.response(200, DirectoryListingSchema)
def browse_directories(query):
    try:
        return list_directories(query.get("path"))
    except PermissionError:
        abort(403, message="That folder cannot be read.", code="directory_unreadable")
    except OSError as exc:
        abort(
            409,
            message=f"Unable to read that folder: {exc.strerror or exc}",
            code="directory_unreadable",
        )


@blp.route("/directories", methods=["POST"])
@blp.arguments(NewDirectorySchema)
@blp.response(201, DirectoryListingSchema)
def make_directory(payload):
    try:
        return create_directory(payload.get("path"), payload["name"])
    except InvalidFolderName as exc:
        abort(400, message=str(exc), code="invalid_folder_name")
    except PermissionError:
        abort(403, message="That folder cannot be written to.", code="directory_not_created")
    except OSError as exc:
        abort(
            409,
            message=f"Unable to create that folder: {exc.strerror or exc}",
            code="directory_not_created",
        )
