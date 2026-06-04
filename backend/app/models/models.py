"""IMPORFACTORY Premium — models/models.py STUB.

Los routers existentes hacen `from models.models import Usuario, UsuarioEmpresa`.
Estos eran modelos SQLAlchemy del ERP. Como IMPORFACTORY no tiene su propia tabla
de usuarios (compartimos auth con el ERP), los reemplazamos por proxies.

Para usar como type hint en Depends(get_current_user) — el objeto real que llega
es `CurrentUser` (de core/security.py).
"""
from core.security import CurrentUser
from core.database import Base


# Alias para que los imports legacy funcionen sin tocar los routers
Usuario = CurrentUser
UsuarioEmpresa = CurrentUser  # placeholder, no se usa en IMPORFACTORY directamente

# Base SQLAlchemy re-exportado desde core/database para que `from models.models import Base` funcione
__all__ = ["CurrentUser", "Usuario", "UsuarioEmpresa", "Base"]



# Stub para que  (services/datil.py legacy) no rompa.
# Las queries reales contra empresa_config usan raw SQL via services/datil_helper.py
class EmpresaConfig:
    empresa_id = None
    clave = None
    valor = None
