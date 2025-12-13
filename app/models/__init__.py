from sqlalchemy.orm import DeclarativeBase
from app.database import Base
from app.models.user import User
from app.models.vm import VM


# # Export wszystkich modeli
# __all__ = [
#     "Base",
#     # Importuj kiedy dodasz nowe modele:
#     # "User", "VM", "Test", "TestTask", "TestResult", "AuditLog"
# ]


from app.models.vm import VM, VMStatus, VMMetadata, AllocatedIP, IPStatus, SSHKey, SSHKeyType, VMIDSequence

__all__ = [
    "VM",
    "VMStatus",
    "VMMetadata",
    "AllocatedIP",
    "IPStatus",
    "SSHKey",
    "SSHKeyType",
    "VMIDSequence",
]
