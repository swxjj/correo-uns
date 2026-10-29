"""Windows Credential Manager only. No generic/fallback plaintext keyring."""
import ctypes
import os
from ctypes import wintypes


class Credential(ctypes.Structure):
    _fields_ = [('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),('CredentialBlobSize',wintypes.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),('Persist',wintypes.DWORD),('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]


class Secrets:
    def __init__(self):
        self.session = {}
        self.available = os.name == 'nt'
        if self.available:
            self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
            self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
            self.api.CredWriteW.restype = wintypes.BOOL
            self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
            self.api.CredReadW.restype = wintypes.BOOL
            self.api.CredFree.argtypes = [ctypes.c_void_p]
            self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD]

    def get(self, key):
        if key in self.session:
            return self.session[key]
        if self.available:
            ptr = ctypes.POINTER(Credential)()
            if self.api.CredReadW('CorreoUNS/'+key, 1, 0, ctypes.byref(ptr)):
                try:
                    return ctypes.string_at(ptr.contents.CredentialBlob, ptr.contents.CredentialBlobSize).decode('utf-16-le')
                finally:
                    self.api.CredFree(ptr)
        return None

    def put(self, key, password, persist=False):
        self.session[key] = password
        if not persist:
            # Session-only must also remove an older persisted password for this target.
            self.forget_persisted(key)
            return False
        if self.available:
            data = password.encode('utf-16-le')
            blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
            cred = Credential(Type=1, TargetName='CorreoUNS/'+key, CredentialBlobSize=len(data), CredentialBlob=blob, Persist=2, UserName='CorreoUNS')
            if self.api.CredWriteW(ctypes.byref(cred), 0):
                return True
        self.forget_persisted(key)
        return False

    def forget_persisted(self, key):
        if self.available:
            self.api.CredDeleteW('CorreoUNS/'+key, 1, 0)

    def forget(self, key):
        self.session.pop(key, None)
        self.forget_persisted(key)
