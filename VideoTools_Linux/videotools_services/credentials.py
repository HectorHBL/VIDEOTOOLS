"""Acceso a almacenes de credenciales del sistema; jamás persiste secretos en archivos."""
from __future__ import annotations
import ctypes
import os
from ctypes import wintypes

SERVICE_NAME = "VideoTools.ElevenLabs"
TARGET_NAME = "VideoTools/ElevenLabsApiKey"

class CredentialError(RuntimeError): pass

def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None

def _windows_write(secret: str) -> None:
    class CREDENTIAL(ctypes.Structure):
        _fields_=[("Flags",wintypes.DWORD),("Type",wintypes.DWORD),("TargetName",wintypes.LPWSTR),("Comment",wintypes.LPWSTR),("LastWritten",ctypes.c_byte*16),("CredentialBlobSize",wintypes.DWORD),("CredentialBlob",ctypes.POINTER(ctypes.c_byte)),("Persist",wintypes.DWORD),("AttributeCount",wintypes.DWORD),("Attributes",ctypes.c_void_p),("TargetAlias",wintypes.LPWSTR),("UserName",wintypes.LPWSTR)]
    raw=secret.encode("utf-16-le");blob=(ctypes.c_byte*len(raw)).from_buffer_copy(raw)
    credential=CREDENTIAL(0,1,TARGET_NAME,None,(ctypes.c_byte*16)(),len(raw),blob,2,0,None,None,"VideoTools")
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(credential),0): raise CredentialError("Windows Credential Manager no pudo guardar la clave.")

def _windows_read() -> str | None:
    pointer=ctypes.c_void_p()
    if not ctypes.windll.advapi32.CredReadW(TARGET_NAME,1,0,ctypes.byref(pointer)):
        return None
    try:
        class CREDENTIAL(ctypes.Structure):
            _fields_=[("Flags",wintypes.DWORD),("Type",wintypes.DWORD),("TargetName",wintypes.LPWSTR),("Comment",wintypes.LPWSTR),("LastWritten",ctypes.c_byte*16),("CredentialBlobSize",wintypes.DWORD),("CredentialBlob",ctypes.POINTER(ctypes.c_byte))]
        credential=ctypes.cast(pointer,ctypes.POINTER(CREDENTIAL)).contents
        return ctypes.string_at(credential.CredentialBlob,credential.CredentialBlobSize).decode("utf-16-le")
    finally: ctypes.windll.advapi32.CredFree(pointer)

def get_elevenlabs_key() -> str | None:
    keyring=_keyring()
    if keyring:
        try:return keyring.get_password(SERVICE_NAME,"api_key")
        except Exception:pass
    return _windows_read() if os.name=="nt" else None

def set_elevenlabs_key(secret: str) -> None:
    if not secret.strip(): raise CredentialError("La API Key no puede estar vacía.")
    keyring=_keyring()
    if keyring:
        try:keyring.set_password(SERVICE_NAME,"api_key",secret.strip());return
        except Exception:pass
    if os.name=="nt":_windows_write(secret.strip());return
    raise CredentialError("No hay GNOME Keyring disponible. Instala el paquete keyring y un backend seguro.")
