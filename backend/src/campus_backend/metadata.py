"""Register feature tables for migration tooling; no business operations."""
from .core.db import Base
from .auth.persistence import models as auth_models
from .catalog.persistence import models as catalog_models
from .profile.persistence import models as profile_models
from .preferences.persistence import models as preferences_models
from .sources.persistence import models as sources_models
from .collection.persistence import models as collection_models
from .notices.persistence import models as notices_models
from .follows.persistence import models as follows_models

metadata = Base.metadata
