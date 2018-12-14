# Copyright (c) 2017, ESET
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Authors: Peter Kalnai <peter.kalnai@eset.cz>;
#          Michal Poslusny <michal.poslusny@eset.cz>
# Date: 2017-09-29
# Version: 1.0
#
# Volatility Framework plugin to detect various types of hooks
# as performed by recent banking Trojans
#
# Usage:
# 1) Move browserhooks.py to volatility/plugins/malware in the
#    Volatilty Framework path.
# 2) Run: python vol.py -f dump_from_compromised_windows_system.vmem
#    --profile=Win7SP1x64 browserhooks (-D _store_mods)
#------------------------------------------------------------------------------------

import os, re, ntpath
import volatility.utils as utils
import volatility.obj as obj
import volatility.debug as debug
import volatility.win32.tasks as tasks
import volatility.win32.modules as modules
import volatility.plugins.malware.malfind as malfind
import volatility.plugins.overlays.basic as basic
import volatility.plugins.procdump as procdump
import volatility.exceptions as exceptions
import volatility.plugins.vadinfo as vadinfo
from volatility.renderers import TreeGrid
from volatility.renderers.basic import Address, Bytes, Hex

try:
    import distorm3
    has_distorm3 = True
except ImportError:
    has_distorm3 = False

try:
    import yara
    has_yara = True
except ImportError:
    has_yara = False

#--------------------------------------------------------------------------------
# Constants
#--------------------------------------------------------------------------------


wow64_types = {'_PEB_LDR_DATA32' : [ 0x30, {
    'Length' : [ 0x0, ['unsigned long']],
    'Initialized' : [ 0x4, ['unsigned char']],
    'SsHandle' : [ 0x8, ['unsigned long', ['void']]],
    'InLoadOrderModuleList' : [ 0xc, ['_LIST_ENTRY32']],
    'InMemoryOrderModuleList' : [ 0x14, ['_LIST_ENTRY32']],
    'InInitializationOrderModuleList' : [ 0x1c, ['_LIST_ENTRY32']],
    'EntryInProgress' : [ 0x24, ['pointer32', ['void']]],
    'ShutdownInProgress' : [ 0x28, ['unsigned char']],
    'ShutdownThreadId' : [ 0x2c, ['pointer32', ['void']]],
    } ],
    '_LIST_ENTRY32' : [ 0x8, {
    'Flink' : [ 0x0, ['pointer32', ['_LIST_ENTRY32']]],
    'Blink' : [ 0x4, ['pointer32', ['_LIST_ENTRY32']]],
    } ],
    '_LDR_DATA_TABLE_ENTRY32' : [ 0x78, {
    'InLoadOrderLinks' : [ 0x0, ['_LIST_ENTRY32']],
    'InMemoryOrderLinks' : [ 0x8, ['_LIST_ENTRY32']],
    'InInitializationOrderLinks' : [ 0x10, ['_LIST_ENTRY32']],
    'DllBase' : [ 0x18, ['pointer32', ['void']]],
    'EntryPoint' : [ 0x1c, ['pointer32', ['void']]],
    'SizeOfImage' : [ 0x20, ['unsigned long']],
    'FullDllName' : [ 0x24, ['_UNICODE_STRING32']],
    'BaseDllName' : [ 0x2c, ['_UNICODE_STRING32']],
    'Flags' : [ 0x34, ['unsigned long']],
    'LoadCount' : [ 0x38, ['unsigned short']],
    'TlsIndex' : [ 0x3a, ['unsigned short']],
    'HashLinks' : [ 0x3c, ['_LIST_ENTRY32']],
    'SectionPointer' : [ 0x3c, ['pointer', ['void']]],
    'CheckSum' : [ 0x40, ['unsigned long']],
    'TimeDateStamp' : [ 0x44, ['unsigned long']],
    'LoadedImports' : [ 0x44, ['pointer', ['void']]],
    'EntryPointActivationContext' : [ 0x48, ['pointer', ['_ACTIVATION_CONTEXT']]],
    'PatchInformation' : [ 0x4c, ['pointer', ['void']]],
    'ForwarderLinks' : [ 0x50, ['_LIST_ENTRY']],
    'ServiceTagLinks' : [ 0x58, ['_LIST_ENTRY']],
    'StaticLinks' : [ 0x60, ['_LIST_ENTRY']],
    'ContextInformation' : [ 0x68, ['pointer', ['void']]],
    'OriginalBase' : [ 0x6c, ['unsigned long']],
    'LoadTime' : [ 0x70, ['_LARGE_INTEGER']],
} ],
'_UNICODE_STRING32' : [ 0x8, {
    'Length' : [ 0x0, ['unsigned short']],
    'MaximumLength' : [ 0x2, ['unsigned short']],
    'Buffer' : [ 0x4, ['pointer32', ['unsigned short']]],
} ],
'_IMAGE_NT_HEADERS32' : [ 0xf8, {
    'Signature' : [ 0x0, ['unsigned long']],
    'FileHeader' : [ 0x4, ['_IMAGE_FILE_HEADER']],
    'OptionalHeader' : [ 0x18, ['_IMAGE_OPTIONAL_HEADER32']],
} ],
'_IMAGE_OPTIONAL_HEADER32' : [ 0xe0, {
    'Magic' : [ 0x0, ['unsigned short']],
    'MajorLinkerVersion' : [ 0x2, ['unsigned char']],
    'MinorLinkerVersion' : [ 0x3, ['unsigned char']],
    'SizeOfCode' : [ 0x4, ['unsigned long']],
    'SizeOfInitializedData' : [ 0x8, ['unsigned long']],
    'SizeOfUninitializedData' : [ 0xc, ['unsigned long']],
    'AddressOfEntryPoint' : [ 0x10, ['unsigned long']],
    'BaseOfCode' : [ 0x14, ['unsigned long']],
    'BaseOfData' : [ 0x18, ['unsigned long']],
    'ImageBase' : [ 0x1c, ['unsigned long']],
    'SectionAlignment' : [ 0x20, ['unsigned long']],
    'FileAlignment' : [ 0x24, ['unsigned long']],
    'MajorOperatingSystemVersion' : [ 0x28, ['unsigned short']],
    'MinorOperatingSystemVersion' : [ 0x2a, ['unsigned short']],
    'MajorImageVersion' : [ 0x2c, ['unsigned short']],
    'MinorImageVersion' : [ 0x2e, ['unsigned short']],
    'MajorSubsystemVersion' : [ 0x30, ['unsigned short']],
    'MinorSubsystemVersion' : [ 0x32, ['unsigned short']],
    'Win32VersionValue' : [ 0x34, ['unsigned long']],
    'SizeOfImage' : [ 0x38, ['unsigned long']],
    'SizeOfHeaders' : [ 0x3c, ['unsigned long']],
    'CheckSum' : [ 0x40, ['unsigned long']],
    'Subsystem' : [ 0x44, ['unsigned short']],
    'DllCharacteristics' : [ 0x46, ['unsigned short']],
    'SizeOfStackReserve' : [ 0x48, ['unsigned long']],
    'SizeOfStackCommit' : [ 0x4c, ['unsigned long']],
    'SizeOfHeapReserve' : [ 0x50, ['unsigned long']],
    'SizeOfHeapCommit' : [ 0x54, ['unsigned long']],
    'LoaderFlags' : [ 0x58, ['unsigned long']],
    'NumberOfRvaAndSizes' : [ 0x5c, ['unsigned long']],
    'DataDirectory' : [ 0x60, ['array', 16, ['_IMAGE_DATA_DIRECTORY']]],
} ],
'_IMAGE_IMPORT_DESCRIPTOR32': [ 0x14, {
    # 0 for terminating null import descriptor
    'OriginalFirstThunk': [ 0x0, ['unsigned int']],
    'TimeDateStamp': [ 0x4, ['unsigned int']],
    'ForwarderChain': [ 0x8, ['unsigned int']],
    'Name': [ 0xC, ['unsigned int']],
    # If bound this has actual addresses
    'FirstThunk': [ 0x10, ['unsigned int']],
    }],
    '_IMAGE_THUNK_DATA32' : [ 0x4, {
    # Fake member for testing if the highest bit is set
    'OrdinalBit' : [ 0x0, ['BitField', dict(start_bit = 31, end_bit = 32)]],
    'Function' : [ 0x0, ['pointer', ['void']]],
    'Ordinal' : [ 0x0, ['unsigned long']],
    'AddressOfData' : [ 0x0, ['unsigned int']],
    'ForwarderString' : [ 0x0, ['unsigned int']],
    }],

}
class _IMAGE_IMPORT_DESCRIPTOR32(obj.CType):
    """Handles IID entries for imported functions"""

    def valid(self, nt_header):
        """Check the validity of some fields"""
        try:
            return (self.OriginalFirstThunk != 0 and
                    self.OriginalFirstThunk < nt_header.OptionalHeader.SizeOfImage and
                    self.FirstThunk != 0 and
                    self.FirstThunk < nt_header.OptionalHeader.SizeOfImage and
                    self.Name < nt_header.OptionalHeader.SizeOfImage)
        except obj.InvalidOffsetError:
            return False

    def _name(self, name_rva):
        """Return a String object for the name at the given RVA"""

        return obj.Object("String",
                      offset = self.obj_parent.DllBase + name_rva,
                      vm = self.obj_native_vm, length = 128)

    def dll_name(self):
        """Returns the name of the DLL for this IID"""
        return self._name(self.Name)

    def _imported_functions(self):
        """
        Generator for imported functions.
        @return: tuple (Ordinal, FunctionVA, Name)
        If the function is imported by ordinal, then Ordinal is the
        ordinal value and Name is None.
        If the function is imported by name, then Ordinal is the
        hint and Name is the imported function name (or None if its
        paged).
        FunctionVA is the virtual address of the imported function,
        as applied to the IAT by the Windows loader. If the FirstThunk
        is paged, then FunctionVA will be None.
        """

        i = 0
        while 1:
            thunk = obj.Object('_IMAGE_THUNK_DATA32',
                       offset = self.obj_parent.DllBase + self.OriginalFirstThunk +
                       i * self.obj_vm.profile.get_obj_size('_IMAGE_THUNK_DATA32'),
                       vm = self.obj_native_vm)

            # We've reached the end when the element is zero
            if thunk == None or thunk.AddressOfData == 0:
                break

            o = obj.NoneObject("Ordinal not accessible?")
            n = obj.NoneObject("Imported by ordinal?")
            f = obj.NoneObject("FirstThunk not accessible")

            # If the highest bit (32 for x86 and 64 for x64) is set, the function is
            # imported by ordinal and the lowest 16-bits contain the ordinal value.
            # Otherwise, the lowest bits (0-31 for x86 and 0-63 for x64) contain an
            # RVA to an _IMAGE_IMPORT_BY_NAME struct.
            if thunk.OrdinalBit == 1:
                o = thunk.Ordinal & 0xFFFF
            else:
                iibn = obj.Object("_IMAGE_IMPORT_BY_NAME",
                                  offset = self.obj_parent.DllBase +
                                  thunk.AddressOfData,
                                  vm = self.obj_native_vm)
                o = iibn.Hint
                n = iibn.Name

            # See if the import is bound (i.e. resolved)
            first_thunk = obj.Object('_IMAGE_THUNK_DATA',
                            offset = self.obj_parent.DllBase + self.FirstThunk +
                            i * self.obj_vm.profile.get_obj_size('_IMAGE_THUNK_DATA32'),
                            vm = self.obj_native_vm)
            if first_thunk:
                f = first_thunk.Function.v()

            yield o, f, str(n or '')
            i += 1

    def is_list_end(self):
        """Returns True if we've reached the list end"""
        data = self.obj_vm.zread(
                        self.obj_offset,
                        self.obj_vm.profile.get_obj_size('_IMAGE_IMPORT_DESCRIPTOR32')
                        )
        return data.count(chr(0)) == len(data)



class _LDR_DATA_TABLE_ENTRY32(obj.CType):
    """
    Class for PE file / modules
    If these classes are instantiated by _EPROCESS.list_*_modules()
    then its guaranteed to be in the process address space.
    FIXME: If these classes are found by modscan, ensure we can
    dereference properly with obj_native_vm.
    """

    def load_time(self):
        if hasattr(self, "LoadTime"):
            return str(self.LoadTime)
        else:
            return ""

    def _nt_header(self):
        """Return the _IMAGE_NT_HEADERS object"""

        try:
            dos_header = obj.Object("_IMAGE_DOS_HEADER", offset = self.DllBase,
                                    vm = self.obj_native_vm)

            return obj.Object("_IMAGE_NT_HEADERS32", offset = dos_header.get_nt_header()._vol_offset, vm = self.obj_native_vm)
        except ValueError:
            return obj.NoneObject("Failed initial sanity checks")
        except exceptions.SanityCheckException:
            return obj.NoneObject("Failed initial sanity checks. Try -u or --unsafe")

    def _directory(self, dir_index):
        """Return the requested IMAGE_DATA_DIRECTORY"""

        nt_header = self._nt_header()
        if nt_header == None:
            raise ValueError('No directory index {0}'.format(dir_index))

        data_dir = nt_header.OptionalHeader.DataDirectory[dir_index]
        if data_dir == None:
            raise ValueError('No directory index {0}'.format(dir_index))

        # Make sure the directory exists
        if data_dir.VirtualAddress == 0 or data_dir.Size == 0:
            raise ValueError('No directory index {0}'.format(dir_index))

        # Make sure the directory VA and Size are sane
        if data_dir.VirtualAddress + data_dir.Size > nt_header.OptionalHeader.SizeOfImage:
            raise ValueError('Invalid directory for index {0}'.format(dir_index))

        return data_dir

    def export_dir(self):
        """Return the IMAGE_DATA_DIRECTORY for exports"""
        return self._directory(0) # DIRECTORY_ENTRY_EXPORT

    def import_dir(self):
        """Return the IMAGE_DATA_DIRECTORY for imports"""
        return self._directory(1) # DIRECTORY_ENTRY_IMPORT

    def debug_dir(self):
        """Return the IMAGE_DEBUG_DIRECTORY for debug info"""
        return self._directory(6) # IMAGE_DEBUG_DIRECTORY

    def security_dir(self):
        """Return the IMAGE_SECURITY_DIRECTORY"""
        return self._directory(4) # IMAGE_DIRECTORY_ENTRY_SECURITY

    def get_debug_directory(self):
        """Return the debug directory object for this PE"""

        try:
            data_dir = self.debug_dir()
        except ValueError, why:
            return obj.NoneObject(str(why))

        return obj.Object("_IMAGE_DEBUG_DIRECTORY",
                          offset = self.DllBase + data_dir.VirtualAddress,
                          vm = self.obj_native_vm)

    def getprocaddress(self, func):
        """Return the RVA of func"""
        for _, f, n in self.exports():
            if str(n or '') == func:
                return f
        return None

    def imports(self):
        """
        Generator for the PE's imported functions.
        The _DIRECTORY_ENTRY_IMPORT.VirtualAddress points to an array
        of _IMAGE_IMPORT_DESCRIPTOR structures. The end is reached when
        the IID structure is all zeros.
        """

        try:
            data_dir = self.import_dir()
        except ValueError, why:
            raise StopIteration(why)

        i = 0

        desc_size = self.obj_vm.profile.get_obj_size('_IMAGE_IMPORT_DESCRIPTOR32')
        while 1:
            desc = obj.Object('_IMAGE_IMPORT_DESCRIPTOR32',
                      vm = self.obj_native_vm,
                      offset = self.DllBase + data_dir.VirtualAddress + (i * desc_size),
                      parent = self)

            # Stop if the IID is paged or all zeros
            if desc == None or desc.is_list_end():
                break

            # Stop if the IID contains invalid fields
            if not desc.valid(self._nt_header()):
                break

            dll_name = desc.dll_name()
            for o, f, n in desc._imported_functions():
                yield dll_name, o, f, n

            i += 1

    def exports(self):
        """Generator for the PE's exported functions"""

        try:
            data_dir = self.export_dir()
        except ValueError, why:
            raise StopIteration(why)

        expdir = obj.Object('_IMAGE_EXPORT_DIRECTORY',
                            offset = self.DllBase + data_dir.VirtualAddress,
                            vm = self.obj_native_vm,
                            parent = self)

        if expdir.valid(self._nt_header()):
            # Ordinal, Function RVA, and Name Object
            for o, f, n in expdir._exported_functions():
                yield o, f, n

class _UNICODE_STRING32(obj.CType):
    """Class representing a _UNICODE_STRING
    Adds the following behavior:
      * The Buffer attribute is presented as a Python string rather
        than a pointer to an unsigned short.
      * The __str__ method returns the value of the Buffer.
    """
    def v(self):
        """
        If the claimed length of the string is acceptable, return a unicode string.
        Otherwise, return a NoneObject.
        """
        data = self.dereference()
        if data:
            return unicode(data)
        return data

    def dereference(self):
        length = self.Length.v()
        if length > 0 and length <= 1024:
            data = self.Buffer.dereference_as('String', encoding = 'utf16', length = length)
            return data
        else:
            return obj.NoneObject("Buffer length {0} for _UNICODE_STRING not within bounds".format(length))

    def proxied(self, _name):
        return str(self)

    def __nonzero__(self):
        ## Unicode strings are valid if they point at a valid memory
        return bool(self.Buffer and self.Length.v() > 0 and self.Length.v() <= 1024)

    def __format__(self, formatspec):
        return format(self.v(), formatspec)

    def __str__(self):
        return str(self.v().encode("utf8", "ignore"))

    def __unicode__(self):
        return unicode(self.dereference())

    def __len__(self):
        return len(self.dereference())

CHROME_SSL_READ_OFFSETS_X86 = {
#chrome_version   DoPayloadRead  SSL_read ssl3_open_app_data
"64.0.3282.119": { 0x00449908, 0x00449B2C, 0x0044ADEE },	
"64.0.3282.140": { 0x00449938, 0x00449B5C, 0x0044AE1E },	
"64.0.3282.167": { 0x00449938, 0x00449B5C, 0x0044AE1E },	
"64.0.3282.186": { 0x00449878, 0x00449A9C, 0x0044AD5E },	
"65.0.3325.146": { 0x00425D22, 0x00425F52, 0x00427264 },	
"65.0.3325.162": { 0x00425D22, 0x00425F52, 0x00427264 },	
"65.0.3325.181": { 0x00425D22, 0x00425F52, 0x00427264 }, 
"66.0.3359.117": { 0x0043B328, 0x0043B558, 0x0043C950 }, 
"66.0.3359.139": { 0x0043B328, 0x0043B558, 0x0043C950 },
"66.0.3359.170": { 0x0043A328, 0x0043A558, 0x0043B950 },
"66.0.3359.181": { 0x0043A328, 0x0043A558, 0x0043B950 },
"67.0.3396.62" : { 0x004833A6, 0x004835D6, 0x004848BA },
"67.0.3396.79" : { 0x004833A6, 0x004835D6, 0x004848BA },	
"67.0.3396.87" : { 0x00483426, 0x00483656, 0x0048493A },	
"67.0.3396.99" : { 0x004834E6, 0x00483716, 0x004849FA },  
"68.0.3440.75" : { 0x003F5A9E, 0x003F5CCE, 0x003F6F32 },
"68.0.3440.84" : { 0x003F5F1E, 0x003F614E, 0x003F73B2 },
"68.0.3440.106": { 0x003F5FBE, 0x003F61EE, 0x003F7452 },
"69.0.3497.81" : { 0x0043B328, 0x0043B558, 0x0043C950 },
"69.0.3497.92" : { 0x0044D388, 0x0044D5B8, 0x0044E62B },
"69.0.3497.100": { 0x0044D388, 0x0044D5B8, 0x0044E62B },
"70.0.3538.67" : { 0x0042A4FA, 0x0042A72A, 0x0042BB2B },
"70.0.3538.77" : { 0x0042A54A, 0x0042A77A, 0x0042BB7B },
"70.0.3538.102": { 0x0042A1CA, 0x0042A3FA, 0x0042B7FB },
"70.0.3538.110": { 0x0042A27A, 0x0042A4AA, 0x0042B8AB }, 
"71.0.3578.80" : { 0x00416F0A, 0x0041713D, 0x0041850B },
"71.0.3578.98" : { 0x0041700A, 0x0041723D, 0x0041860B },
}

CHROME_SSL_WRITE_OFFSETS_X86 = {
#chrome_version  DoPayloadWrite SSL_write ssl3_write_app_data
"64.0.3282.119": { 0x00448D8E, 0x00448E87, 0x00448F6B },	
"64.0.3282.140": { 0x00448DBE, 0x00448EB7, 0x00448F9B },	
"64.0.3282.167": { 0x00448DBE, 0x00448EB7, 0x00448F9B },	
"64.0.3282.186": { 0x00448CFE, 0x00448DF7, 0x00448EDB },	
"65.0.3325.146": { 0x00425194, 0x00425291, 0x00425379 },	
"65.0.3325.162": { 0x00425194, 0x00425291, 0x00425379 },	
"65.0.3325.181": { 0x00425194, 0x00425291, 0x00425379 }, 
"66.0.3359.117": { 0x0043A57C, 0x0043A679, 0x0043A761 },	
"66.0.3359.139": { 0x0043A57C, 0x0043A679, 0x0043A761 },	
"66.0.3359.170": { 0x0043957C, 0x00439679, 0x00439761 },	
"66.0.3359.181": { 0x0043957C, 0x00439679, 0x00439761 },	
"67.0.3396.62" : { 0x0048273C, 0x00482839, 0x00482921 },	
"67.0.3396.79" : { 0x0048273C, 0x00482839, 0x00482921 },	
"67.0.3396.87" : { 0x004827BC, 0x004828B9, 0x004829A1 },	
"67.0.3396.99" : { 0x0048287C, 0x00482979, 0x00482A61 },  
"68.0.3440.75" : { 0x003F4E4E, 0x003F4F4B, 0x003F5033 },
"68.0.3440.84" : { 0x003F52CE, 0x003F53CB, 0x003F54B3 },
"68.0.3440.106": { 0x003F536E, 0x003F546B, 0x003F5553 },
"69.0.3497.81" : { 0x0043A57C, 0x0043A679, 0x0043A761 },
"69.0.3497.92" : { 0x0044C5C8, 0x0044C6C5, 0x0044C7AB },
"69.0.3497.100": { 0x0044C5C8, 0x0044C6C5, 0x0044C7AB },
"70.0.3538.67" : { 0x004297AE, 0x004298AB, 0x00429991 },
"70.0.3538.77" : { 0x004297FE, 0x004298FB, 0x004299E1 },
"70.0.3538.102": { 0x0042947E, 0x0042957B, 0x00429661 },
"70.0.3538.110": { 0x0042952E, 0x0042962B, 0x00429711 },
"71.0.3578.80" : { 0x004161BE, 0x004162BB, 0x004163A1 },
"71.0.3578.98" : { 0x004162BE, 0x004163BB, 0x004164A1 },
}

CHROME_SSL_OTHER_OFFSETS_X86 = {
#chrome_version    SSL_new      ssl3_new    SSL_free    ssl3_free
"64.0.3282.119": { 0x00380A7C, 0x00380F50, 0xFFFFFFFF, 0xFFFFFFFF }, #January 24, 2018
"64.0.3282.140": { 0x00380A7C, 0x00380F50, 0xFFFFFFFF, 0xFFFFFFFF }, #February 1, 2018
"64.0.3282.167": { 0x00380A7C, 0x00380F50, 0xFFFFFFFF, 0xFFFFFFFF }, #February 13, 2018
"64.0.3282.186": { 0x0038095C, 0x00380E30, 0xFFFFFFFF, 0xFFFFFFFF }, #February 22, 2018
"65.0.3325.146": { 0x0036199C, 0x00361E70, 0xFFFFFFFF, 0xFFFFFFFF }, #March 6, 2018
"65.0.3325.162": { 0x0036199C, 0x00361E70, 0xFFFFFFFF, 0xFFFFFFFF }, #March 13, 2018
"65.0.3325.181": { 0x0036199C, 0x00361E70, 0xFFFFFFFF, 0xFFFFFFFF }, #March 20, 2018
"66.0.3359.117": { 0x003FFE0A, 0x004002F4, 0x0043B5E9, 0x0060FBD0 }, #April 17, 2018
"66.0.3359.139": { 0x003FFE0A, 0x004002F4, 0x0043B5E9, 0x0060FBD0 }, #April 26, 2018
"66.0.3359.170": { 0x003FEE9A, 0x003FF384, 0x0043A5E9, 0x0060EBD0 }, #May 10, 2018
"66.0.3359.181": { 0x003FEE9A, 0x003FF384, 0x0043A5E9, 0x0060EBD0 }, #May 15, 2018
"67.0.3396.62" : { 0x0042DE74, 0x0042E35E, 0x005A41AB, 0x005A4457 }, #May 29, 2018
"67.0.3396.79" : { 0x0042DE74, 0x0042E35E, 0x005A41AB, 0x005A4457 }, #June 6, 2018
"67.0.3396.87" : { 0x0042DF04, 0x0042E3EE, 0x005A423D, 0x005A44E9 }, #June 12, 2018
"67.0.3396.99" : { 0x0042DF94, 0x0042E47E, 0x005A431B, 0x005A45C7 }, #June 25, 2018
"68.0.3440.75" : { 0x003AE754, 0x003AEB8D, 0x004F757B, 0x004F7754 }, #July 24, 2018
"68.0.3440.84" : { 0x003AEBD4, 0x003AF00D, 0x004F7A5B, 0x004F7C34 }, #July 31, 2018
"68.0.3440.106": { 0x003AEC74, 0x003AF0AD, 0x004F7B0B, 0x004F7CE4 }, #August 8, 2018 
"69.0.3497.81" : { 0x003FFE0A, 0x004002F4, 0x0043B5E9, 0x0060FBD0 }, #September 4, 2018
"69.0.3497.92" : { 0x003C838B, 0x003C8936, 0x0055BD87, 0x0055BE99 }, #September 11, 2018
"69.0.3497.100": { 0x003C838B, 0x003C8936, 0x0055BD87, 0x0055BE99 }, #September 17, 2018
"70.0.3538.67" : { 0x003F50E3, 0x003F57E0, 0x006278CD, 0x00627980 }, #October 16, 2018
"70.0.3538.77" : { 0x003F5133, 0x003F5830, 0x006278DD, 0x00627990 }, #October 24, 2018
"70.0.3538.102": { 0x003F4DB3, 0x003F54B0, 0x006275ED, 0x006276A0 }, #November 9, 2018
"70.0.3538.110": { 0x003F4E63, 0x003F5560, 0x0062771D, 0x006277D0 }, #November 19, 2018
"71.0.3578.80" : { 0x003E2E1F, 0x003E3542, 0x0060A45D, 0x0060A510 }, #December 4, 2018
"71.0.3578.98" : { 0x003E2F1F, 0x003E3642, 0x0060A54D, 0x0060A600 }, #December 12, 2018
}

CHROME_SSL_READ_OFFSETS_X64 = {
#chrome_version       DoPayloadRead         SSL_read       ssl3_open_app_data             
"64.0.3282.119": { 0x00000000004F6A9C, 0x00000000004F6CCA, 0x00000000004F8209 }, 
"64.0.3282.140": { 0x00000000004F6B2C, 0x00000000004F6D5A, 0x00000000004F8299 }, 
"64.0.3282.167": { 0x00000000004F6B2C, 0x00000000004F6D5A, 0x00000000004F8299 }, 
"64.0.3282.186": { 0x00000000004F6A1C, 0x00000000004F6C4A, 0x00000000004F8189 },	
"65.0.3325.146": { 0x00000000004CE152, 0x00000000004CE395, 0x00000000004CF94F },	
"65.0.3325.162": { 0x00000000004CE152, 0x00000000004CE395, 0x00000000004CF94F },	
"65.0.3325.181": { 0x00000000004CE192, 0x00000000004CE3D5, 0x00000000004CF98F }, 
"66.0.3359.117": { 0x00000000004FCDAA, 0x00000000004FCFED, 0x00000000004FE677 },
"66.0.3359.139": { 0x00000000004FCDCA, 0x00000000004FD00D, 0x00000000004FE697 },
"66.0.3359.170": { 0x00000000004FCCCA, 0x00000000004FCF0D, 0x00000000004FE597 },
"66.0.3359.181": { 0x00000000004FCCDA, 0x00000000004FCF1D, 0x00000000004FE5A7 },
"67.0.3396.62" : { 0x0000000000610C22, 0x0000000000610E65, 0x0000000000612413 },
"67.0.3396.79" : { 0x0000000000610C12, 0x0000000000610E55, 0x0000000000612403 },
"67.0.3396.87" : { 0x0000000000610CC2, 0x0000000000610F05, 0x00000000006124B3 },
"67.0.3396.99" : { 0x0000000000610D22, 0x0000000000610F65, 0x0000000000612513 },
"68.0.3440.75" : { 0x000000000056B186, 0x000000000056B3C9, 0x000000000056C8D5 },
"68.0.3440.84" : { 0x000000000056B566, 0x000000000056B7A9, 0x000000000056CCB5 },
"68.0.3440.106": { 0x000000000056B646, 0x000000000056B889, 0x000000000056CD95 },
"69.0.3497.81" : { 0x00000000004E078A, 0x00000000004E09CD, 0x00000000004E2982 },
"69.0.3497.92" : { 0x00000000004E07CA, 0x00000000004E0A0D, 0x00000000004E29C2 },
"69.0.3497.100": { 0x00000000004E07DA, 0x00000000004E0A1D, 0x00000000004E29D2 },
"70.0.3538.67" : { 0x000000000053BEFA, 0x000000000053C13D, 0x000000000053DAEC },
"70.0.3538.77" : { 0x000000000053BEFA, 0x000000000053C13D, 0x000000000053DAEC },
"70.0.3538.102": { 0x000000000053BBEA, 0x000000000053BE2D, 0x000000000053D7DC },
"70.0.3538.110": { 0x000000000053BD2A, 0x000000000053BF6D, 0x000000000053D91C },
"71.0.3578.80" : { 0x00000000005260AC, 0x00000000005262EF, 0x0000000000527C7E },
"71.0.3578.98" : { 0x000000000052617C, 0x00000000005263BF, 0x0000000000527D4E },
}

CHROME_SSL_WRITE_OFFSETS_X64 = {
#chrome_version      DoPayloadWrite        SSL_write       ssl3_write_app_data             
"64.0.3282.119": { 0x00000000004F5D38, 0x00000000004F5E5E, 0x00000000004F5F7F },	
"64.0.3282.140": { 0x00000000004F5DC8, 0x00000000004F5EEE, 0x00000000004F600F },	
"64.0.3282.167": { 0x00000000004F5DC8, 0x00000000004F5EEE, 0x00000000004F600F },	
"64.0.3282.186": { 0x00000000004F5CB8, 0x00000000004F5DDE, 0x00000000004F5EFF },	
"65.0.3325.146": { 0x00000000004CD3D0, 0x00000000004CD4FC, 0x00000000004CD623 },	
"65.0.3325.162": { 0x00000000004CD3D0, 0x00000000004CD4FC, 0x00000000004CD623 },	
"65.0.3325.181": { 0x00000000004CD410, 0x00000000004CD53C, 0x00000000004CD663 }, 
"66.0.3359.117": { 0x00000000004FBDA4, 0x00000000004FBED0, 0x00000000004FBFF7 },
"66.0.3359.139": { 0x00000000004FBDC4, 0x00000000004FBEF0, 0x00000000004FC017 },
"66.0.3359.170": { 0x00000000004FBCC4, 0x00000000004FBDF0, 0x00000000004FBF17 },
"66.0.3359.181": { 0x00000000004FBCD4, 0x00000000004FBE00, 0x00000000004FBF27 },
"67.0.3396.62" : { 0x000000000060FD96, 0x000000000060FEC2, 0x000000000060FFE9 },
"67.0.3396.79" : { 0x000000000060FD86, 0x000000000060FEB2, 0x000000000060FFD9 },
"67.0.3396.87" : { 0x000000000060FE36, 0x000000000060FF62, 0x0000000000610089 },
"67.0.3396.99" : { 0x000000000060FE96, 0x000000000060FFC2, 0x00000000006100E9 },
"68.0.3440.75" : { 0x000000000056A350, 0x000000000056A47C, 0x000000000056A5A3 },
"68.0.3440.84" : { 0x000000000056A730, 0x000000000056A85C, 0x000000000056A983 },
"68.0.3440.106": { 0x000000000056A810, 0x000000000056A93C, 0x000000000056AA63 },
"69.0.3497.81" : { 0x00000000004DF7A8, 0x00000000004DF8D4, 0x00000000004DF9F9 },
"69.0.3497.92" : { 0x00000000004DF7E8, 0x00000000004DF914, 0x00000000004DFA39 },
"69.0.3497.100": { 0x00000000004DF7F8, 0x00000000004DF924, 0x00000000004DFA49 },
"70.0.3538.67" : { 0x000000000053AFAC, 0x000000000053B0D8, 0x000000000053B1FD },
"70.0.3538.77" : { 0x000000000053AFAC, 0x000000000053B0D8, 0x000000000053B1FD },
"70.0.3538.102": { 0x000000000053AC9C, 0x000000000053ADC8, 0x000000000053AEED },
"70.0.3538.110": { 0x000000000053ADDC, 0x000000000053AF08, 0x000000000053B02D },
"71.0.3578.80" : { 0x000000000052515E, 0x000000000052528A, 0x00000000005253AF },
"71.0.3578.98" : { 0x000000000052522E, 0x000000000052535A, 0x000000000052547F },
}

CHROME_SSL_OTHER_OFFSETS_X64 = {
#chrome_version          SSL_new             ssl3_new            SSL_free           ssl3_free
"64.0.3282.119": { 0x0000000000421D22, 0x0000000000422299, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF },	
"64.0.3282.140": { 0x0000000000421D12, 0x0000000000422289, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF },	
"64.0.3282.167": { 0x0000000000421D12, 0x0000000000422289, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF },	
"64.0.3282.186": { 0x0000000000421BF2, 0x0000000000422169, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF },	
"65.0.3325.146": { 0x0000000000400567, 0x0000000000400ADB, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF },	
"65.0.3325.162": { 0x0000000000400567, 0x0000000000400ADB, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF },	
"65.0.3325.181": { 0x0000000000400597, 0x0000000000400B0B, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF }, 
"66.0.3359.117": { 0x0000000000486E0E, 0x0000000000487398, 0x00000000004FD08E, 0x000000000064960B },
"66.0.3359.139": { 0x0000000000486E2E, 0x00000000004873B8, 0x00000000004FD0AE, 0x000000000064962B },
"66.0.3359.170": { 0x0000000000486D4E, 0x00000000004872D8, 0x00000000004FCFAE, 0x00000000006483CB },
"66.0.3359.181": { 0x0000000000486D5E, 0x00000000004872E8, 0x00000000004FCFBE, 0x00000000006483DB },
"67.0.3396.62" : { 0x00000000004B9210, 0x00000000004B979A, 0x00000000006A66BC, 0x00000000006A697B },
"67.0.3396.79" : { 0x00000000004B9200, 0x00000000004B978A, 0x00000000006A66AC, 0x00000000006A696B },
"67.0.3396.87" : { 0x00000000004B92A0, 0x00000000004B982A, 0x00000000006A675C, 0x00000000006A6A1B },
"67.0.3396.99" : { 0x00000000004B9300, 0x00000000004B988A, 0x00000000006A67BC, 0x00000000006A6A7B }, 
"68.0.3440.75" : { 0x0000000000432E20, 0x000000000043333C, 0x00000000005E5426, 0x00000000005E560E },
"68.0.3440.84" : { 0x00000000004331F0, 0x000000000043370C, 0x00000000005E5806, 0x00000000005E59EE },
"68.0.3440.106": { 0x00000000004332C0, 0x00000000004337DC, 0x00000000005E58E6, 0x00000000005E5ACE },
"69.0.3497.81" : { 0x000000000048B26E, 0x000000000048B913, 0x000000000062006D, 0x0000000000620193 },
"69.0.3497.92" : { 0x000000000048B2AE, 0x000000000048B953, 0x00000000006200AD, 0x00000000006201D3 },
"69.0.3497.100": { 0x000000000048B2BE, 0x000000000048B963, 0x00000000006200BD, 0x00000000006201E3 },
"70.0.3538.67" : { 0x00000000004AFFAF, 0x00000000004B07A7, 0x000000000073A65A, 0x000000000073A71D },
"70.0.3538.77" : { 0x00000000004AFFAF, 0x00000000004B07A7, 0x000000000073A67A, 0x000000000073A73D },
"70.0.3538.102": { 0x00000000004AFCAF, 0x00000000004B04A7, 0x000000000073A41A, 0x000000000073A4DD },
"70.0.3538.110": { 0x00000000004AFDAF, 0x00000000004B05A7, 0x000000000073A52A, 0x000000000073A5ED },
"71.0.3578.80" : { 0x000000000049BB8A, 0x000000000049C3C1, 0x00000000007195E4, 0x00000000007196A7 },
"71.0.3578.98" : { 0x000000000049BC6A, 0x000000000049C4A1, 0x0000000000719694, 0x0000000000719757 },
}

IMAGE_NT_OPTIONAL_HDR32_MAGIC = 0x010B
IMAGE_NT_OPTIONAL_HDR64_MAGIC = 0x020B

# hook types
HOOKTYPE_IAT = 4
HOOKTYPE_EAT = 8
HOOKTYPE_INLINE = 16
HOOKTYPE_IRP = 256
HOOKTYPE_WINSOCK = 512
HOOKTYPE_INLINE_CHROME_V64_SSL_READ = 1024
HOOKTYPE_INLINE_CHROME_V64_SSL_WRITE = 2048
HOOKTYPE_INLINE_CHROME_V64_SSL_OTHER = 4096

# names for hook types
hook_type_strings = {
    HOOKTYPE_IAT             : "Import Address Table (IAT)",
    HOOKTYPE_EAT             : "Export Address Table (EAT)",
    HOOKTYPE_INLINE          : "Inline/Trampoline",
    HOOKTYPE_WINSOCK         : "Winsock Procedure Table Hook",
    HOOKTYPE_INLINE_CHROME_V64_SSL_READ : "SSL read related hooks for Chrome version 64+",
    HOOKTYPE_INLINE_CHROME_V64_SSL_WRITE : "SSL write related hooks for Chrome version 64+",
    HOOKTYPE_INLINE_CHROME_V64_SSL_OTHER : "Other SSL hooks for Chrome version 64+"
}

#--------------------------------------------------------------------------------
# Profile Modifications
#--------------------------------------------------------------------------------

class vad_ck():
    def get_vad_end(self, task, address):
        for vad in task.VadRoot.traverse():
            if address == vad.Start:
                return vad.End+1
        return None

    def get_vad_base(self, task, address):
        """ Get the VAD starting address """

        for vad in task.VadRoot.traverse():
            #print "vad.Start %X"%(vad.Start)
            #print "vad.End %X"%(vad.End)
            #print "address %X"%(address)
            if address >= vad.Start and address < vad.End:
                return vad.Start

        # This should never really happen
        return None

#--------------------------------------------------------------------------------
# Module Group Class
#--------------------------------------------------------------------------------

class ModuleGroup(object):
    """A class to assist with module lookups"""

    def __init__(self, mod_list):
        """Initialize.

        @param mod_list: a list of _LDR_DATA_TABLE_ENTRY objects.
        This can be a generator.
        """

        self.mods = list(mod_list)
        self.mod_name = {}
        self.mod_fast = [(mod.DllBase, mod.DllBase + mod.SizeOfImage, mod) for mod in self.mods]

        for mod in self.mods:
            name = str(mod.BaseDllName or '').lower()

            if name in self.mod_name:
                self.mod_name[name].append(mod)
            else:
                self.mod_name[name] = [mod]

    def find_module(self, address):
        """Find a module by an address it contains.

        @param address: location in process or kernel AS to
        find an owning module.

        When performing thousands of lookups, this method
        is actually quicker than tasks.find_module.
        """

        for base, end, mod in self.mod_fast:
            if address >= base and address <= end:
                return mod

        return obj.NoneObject("")

#--------------------------------------------------------------------------------
# Hook Class
#--------------------------------------------------------------------------------

class Hook(object):
    """A class for API hooks. It helps organize the many
    pieces of information required to report on the hook."""

    def __init__(self, hook_type, function_name,
                        function_address = None, hook_address = None,
                        hook_module = None, victim_module = None,
                        decode_bits = distorm3.Decode32Bits):
        """
        Initalize a hook class instance.

        @params hook_type: one of the HOOK_TYPE_* constants

        @params function_name: name of the function being hooked

        @params function_address: address of the hooked function in
            process or kernel memory.

        @params hook_address: address where the hooked function
            actually points.

        @params hook_module: the _LDR_DATA_TABLE_ENTRY of the
            hooking module (owner of the hook_address). note:
            this can be None if the module cannot be identified.

        @params victim_module: the _LDR_DATA_TABLE_ENTRY of the
            module being hooked (contains the function_address).
            note: this can be a string if checking IAT hooks.

        """
        self.hook_type = hook_type
        self.function_name = function_name
        self.function_address = function_address
        self.hook_address = hook_address
        self.hook_module = hook_module
        self.victim_module = victim_module
        self.decode_bits = decode_bits
        # List of tuples: address, data pairs
        self.disassembled_hops = []

    def add_hop_chunk(self, address, data):
        """Support disassembly for multiple hops"""
        self.disassembled_hops.append((address, data))

    def _module_name(self, module):
        """Return a sanitized module name"""

        # The module can't be identified
        if not module:
            return '<unknown>'

        # The module is a string name like "ntdll.dll"
        if isinstance(module, basic.String) or isinstance(module, str):
            return str(module)

        # The module is a _LDR_DATA_TABLE_ENTRY
        return str(module.BaseDllName or '') or str(module.FullDllName or '') or '<unknown>'

    @property
    def Type(self):
        """Translate the hook type into a string"""
        return hook_type_strings.get(self.hook_type, "")

    @property
    def Function(self):
        """Return the function name if its available"""
        return str(self.function_name) or '<unknown>'

    @property
    def Detail(self):
        """The detail depends on the hook type"""
        if self.hook_type == HOOKTYPE_IAT:
            return "{0}!{1}".format(self.VictimModule, self.Function)
        elif self.hook_type == HOOKTYPE_EAT:
            return "{0} at {1:#x}".format(self.Function, self.hook_address)
        elif self.hook_type == HOOKTYPE_INLINE:
            return "{0}!{1} at {2:#x}".format(self.VictimModule, self.Function, self.function_address)
        else:
            return self.Function

    @property
    def HookModule(self):
        """Name of the hooking module"""
        return self._module_name(self.hook_module)

    @property
    def VictimModule(self):
        """Name of the victim module"""
        return self._module_name(self.victim_module)

#--------------------------------------------------------------------------------
# Whitelist Rules
#--------------------------------------------------------------------------------

# The values of each dictionary item is a list of tuples which are regexes
# in the format (process, srd_mod, dst_mod, function). If you specify
# (".*", ".*", ".*", ".*") then you essentially whitelist all possible hooks
# of the given type.

whitelist_rules = {
    HOOKTYPE_IAT : [
    # Ignore hooks that point inside C runtime libraries
    (".*", ".*", "(msvcr|msvcp).+\.dll", ".*"),
    # Ignore hooks of WMI that point inside advapi32.dll
    (".*", "wmi.dll", "advapi32.dll", ".*"),
    # Ignore hooks of winsock that point inside ws2 and   mswsock
    (".*", "WSOCK32.dll", "(WS2_32|MSWSOCK)\.dll", ".*"),
    # Ignore hooks of SCHANNEL* that point inside secur32.dll
    (".*", "schannel.dll", "secur32.dll", ".*"),
    # Ignore hooks of Secur32* that point inside SSPICLI
    (".*", "Secur32.dll", "SSPICLI.DLL", ".*"),
    #(".*", "WININET.dll", "IEShims.dll", ".*"),
    (".*", "shlwapi.dll", "IEShims.dll", ".*"),
    # Ignore hooks that point inside known modules
    (".*", ".*", "(kernel32|gdi32|advapi32|ntdll|shimeng|kernelbase|shlwapi|user32|cfgmgr32)", ".*"),
    # Handle some known forwarded imports
    (".*", ".*", ".*", "((Enter|Delete|Leave)CriticalSection|(Get|Set)LastError|Heap(ReAlloc|Free|Size|Alloc)|Rtl(Unwind|MoveMemory))"),
    # Ignore sfc hooks going to sfc_os
    (".*", "sfc\.dll", "sfc_os\.dll", ".*"),
    # Ignore netapi32 hooks pointing at netutils or samcli or wkscli
    (".*", "netapi32\.dll", "(netutils|samcli|wkscli)\.dll", ".*"),
    (".*", "setupapi\.dll", "devrtl\.dll", ".*"),
    (".*", "kernel32\.dll", ".*", ".*"),
    (".*", "advapi32\.dll", ".*", ".*"),
    ("chrome\.exe", ".*", ".*",".*"),
    (".*", ".*", "ntdll\.dll", ".*"),
    (".*", ".*", "kernel32\.dll", ".*"),
    #Mozilla Firefox browser exclusions
    (".*", ".*", "ucrtbase\.DLL", ".*"),

    ],
    HOOKTYPE_INLINE : [
    # Ignore hooks in the pywin32 service process
    ("pythonservice", ".*", ".*", ".*"),
    # Many legit hooks land inside these modules
    (".*", ".*", "(msvcr|advapi32|version|wbemcomn|ntdll|kernel32|kernelbase|sechost|ole32|shlwapi|user32|gdi32|ws2_32|shell32|imm32|propsys)", ".*"),
    # Ignore hooks of the c runtime DLLs
    (".*", "(msvc(p|r)\d{2}|mfc\d{2})\.dll", ".*", ".*"),
    # This is a global variable
    (".*", "msvcrt\.dll", ".*", "_acmdln"),
    # Ignore hooks of common firefox components
    #PK ("firefox\.exe", ".*", "(xul|mozcrt|nspr4)", ".*"),
    # Ignore hooks of certain components in iexplore
    ("iexplore\.exe", ".*", "(IEFRAME)", ".*"),
    ("chrome\.exe", ".*", "(ntdll)", ".*"),
    ("chrome\.dll", ".*", "(ntdll)", ".*"),
    ("ntdll\.dll", ".*", ".*", ".*"),

    # Ignore DLL registration functions
    (".*", ".*", ".*", "(DllCanUnloadNow|DllRegisterServer|DllUnregisterServer)"),
    # Ignore netapi32 hooks pointing at netutils
    (".*", "netapi32\.dll", "netutils\.dll", ".*"),
    #Mozilla Firefox browser exclusions
    (".*", ".*", "mozglue\.dll", ".*"),
    ],
}

class BrowserHooks(procdump.ProcDump):
    """Detect hooks in process memory of important browsers"""

    def __init__(self, config, *args, **kwargs):
        procdump.ProcDump.__init__(self, config, *args, **kwargs)
        config.remove_option("MEMORY")

        self.compiled_rules = self.compile()

        self.critical_process = ["iexplore.exe", "firefox.exe", "chrome.exe", "microsoftedgecp.exe"]

        self.critical_dlls = ["ws2_32.dll", "wininet.dll", "chrome.dll", "nss3.dll", "nspr4.dll"]


    def compile(self):
        """
        Precompile the regular expression rules. Its quicker
        if we do this once per plugin run, rather than once per
        API hook that needs checking.
        """
        ret = dict()
        for key, rules in whitelist_rules.items():
            for rule in rules:
                ruleset = ((re.compile(rule[0], re.I), # Process name
                            re.compile(rule[1], re.I), # Source module
                            re.compile(rule[2], re.I), # Destination module
                            re.compile(rule[3], re.I), # Function name
                            ))
                if ret.has_key(key):
                    ret[key].append(ruleset)
                else:
                    ret[key] = [ruleset]
        return ret

    def whitelist(self, rule_key, process, src_mod, dst_mod, function):
        """Check if an API hook should be ignored due to whitelisting.

        @param rule_key: a key from the whitelist_rules dictionary which
            describes the type of hook (i.e. Usermode IAT or Kernel Inline).

        @param process: name of the suspected victim process.

        @param src_mod: name of the source module whose function has been
            hooked. this varies depending on whether we're dealing with IAT
            EAT, inline, etc.

        @param dst_mod: name of the module that is the destination of the
            hook pointer. this is usually the rootkit dll, exe, or sys,
            however, in many cases there is no module name since the rootkit
            is trying to be stealthy.

        @param function: name of the function that has been hooked.
        """
        # There are no whitelist rules for this hook type
        if rule_key not in self.compiled_rules:
            return False

        for rule in self.compiled_rules[rule_key]:
            if (rule[0].search(process) != None and
                    rule[1].search(src_mod) != None and
                    rule[2].search(dst_mod) != None and
                    rule[3].search(function) != None):
                return True

        return False


    def filter_tasks(self, procs):
        #PK procs = PSList(self._config).calculate()

        tasks_filt = []
        for task in procs:
            pid = task.UniqueProcessId
            process_name = str(task.ImageFileName).lower()
            if process_name not in self.critical_process:
                continue
            #PK print "process_name %s; PID: %u IsWow64 %u"%(process_name, pid,task.IsWow64)
            tasks_filt.append(task)
        return tasks_filt

    @staticmethod
    def check_inline(va, addr_space, mem_start, mem_end, mode = distorm3.Decode32Bits):
        """
        Check for inline API hooks. We check for direct and indirect
        calls, direct and indirect jumps, and PUSH/RET combinations.

        @param va: the virtual address of the function to check

        @param addr_space: process or kernel AS where the function resides

        @param mem_start: base address of the module containing the
            function being checked.

        @param mem_end: end address of the module containing the func
            being checked.

        @param mode: 32 or 64 bit mode (default: 32)

        @returns: a tuple of (hooked, data, hook_address)
        """

        data = addr_space.zread(va, 24)

        if data == "\x00" * len(data):
            #debug.debug("Cannot read function prologue at {0:#x}".format(va))
            return None

        outside_module = lambda x: x != None and (x < mem_start or x > mem_end)

        # Number of instructions disassembled so far
        n = 0
        # Destination address of hooks
        d = None
        # Save the last PUSH before a CALL
        push_val = None
        # Save the general purpose registers
        regs = {}

        for op in distorm3.Decompose(va, data, mode):

            # Quit the loop when we have three instructions or when
            # a decomposition error is encountered, whichever is first.
            if not op.valid or n == 3:
                break

            if mode == distorm3.Decode64Bits:
                if op.flowControl == 'FC_CALL':
                    pass
                elif op.flowControl == 'FC_UNC_BRANCH' and op.mnemonic.startswith("JMP"):
                    if ('FLAG_RIP_RELATIVE' in op.flags and
                            op.operands[0].type == 'AbsoluteMemory'):

                        const = op.address + op.size + op.operands[0].disp
                        d = obj.Object("unsigned long long", offset = const, vm = addr_space)
                        if outside_module(d):
                            break
                    elif op.operands[0].type == 'Immediate':
                        # Check for JMP ADDR
                        d = op.operands[0].value
                        if outside_module(d):
                            break
                    elif op.operands[0].type == 'FarMemory':
                        # Check for JMP FAR ADDR
                        d = op.operands[0].off
                        if outside_module(d):
                            break
                elif op.flowControl == 'FC_NONE':
                    pass
                elif op.flowControl == 'FC_RET':
                    pass
            elif mode == distorm3.Decode32Bits:
                if op.flowControl == 'FC_CALL':
                    # Clear the push value
                    if push_val:
                        push_val = None
                    if op.mnemonic == "CALL" and op.operands[0].type == 'AbsoluteMemoryAddress':
                        # Check for CALL [ADDR]
                        const = op.operands[0].disp & 0xFFFFFFFF
                        d = obj.Object("unsigned int", offset = const, vm = addr_space)
                        if outside_module(d):
                            break
                    elif op.operands[0].type == 'Immediate':
                        # Check for CALL ADDR
                        d = op.operands[0].value & 0xFFFFFFFF
                        if outside_module(d):
                            break
                    elif op.operands[0].type == 'Register':
                        # Check for CALL REG
                        d = regs.get(op.operands[0].name)
                        if d and outside_module(d):
                            break
                elif op.flowControl == 'FC_UNC_BRANCH' and op.mnemonic.startswith("JMP"):
                    # Clear the push value
                    if push_val:
                        push_val = None
                    if op.size > 2:
                        if op.operands[0].type == 'AbsoluteMemoryAddress':
                            # Check for JMP [ADDR]
                            const = op.operands[0].disp & 0xFFFFFFFF
                            d = obj.Object("unsigned int", offset = const, vm = addr_space)
                            if outside_module(d):
                                break
                        elif op.operands[0].type == 'Immediate':
                            # Check for JMP ADDR
                            d = op.operands[0].value & 0xFFFFFFFF
                            if outside_module(d):
                                break
                        elif op.operands[0].type == 'FarMemory':
                            # Check for JMP FAR ADDR
                            d = op.operands[0].off
                            if outside_module(d):
                                break
                    elif op.size == 2 and op.operands[0].type == 'Register':
                        # Check for JMP REG
                        d = regs.get(op.operands[0].name)
                        if d and outside_module(d):
                            break
                elif op.flowControl == 'FC_NONE':
                    # Check for PUSH followed by a RET
                    if (op.mnemonic == "PUSH" and
                            op.operands[0].type == 'Immediate' and op.size == 5):
                        # Set the push value
                        push_val = op.operands[0].value & 0xFFFFFFFF
                    # Check for moving imm values into a register
                    if (op.mnemonic == "MOV" and op.operands[0].type == 'Register'
                            and op.operands[1].type == 'Immediate'):
                        # Clear the push value
                        if push_val:
                            push_val = None
                        # Save the value put into the register
                        regs[op.operands[0].name] = op.operands[1].value
                elif op.flowControl == 'FC_RET':
                    if push_val:
                        d = push_val
                        if outside_module(d):
                            break
            n += 1

        # Check EIP after the function prologue
        if outside_module(d):
            #PK print("Hook found: 0x%X"%(d))
            return True, data, d

        else:
            return False, data, d

    def gather_stuff(self, _addr_space, module):
        """Use the Volatility object classes to enumerate
        imports and exports. This function can be overriden
        to use pefile instead for speed testing"""

        # This is a dictionary where keys are the names of imported
        # modules and values are lists of tuples (ord, addr, name).
        imports = {}
        exports = [(o, module.DllBase + f, n) for o, f, n in module.exports()]

        for dll, o, f, n in module.imports():
            dll = dll.lower()
            if dll in imports:
                imports[dll].append((o, f, n))
            else:
                imports[dll] = [(o, f, n)]

        return imports, exports



    def get_file_version(self, module, addr_space):
        full_module_name = "{0}".format(module.FullDllName)
        full_module_name_parts = full_module_name.split("\\")
        pefile = obj.Object("_IMAGE_DOS_HEADER", module.DllBase, addr_space)
        if pefile.is_valid():
            vinfo = pefile.get_version_info()
            if vinfo != None:
                vinfo_ver ="{0}".format(vinfo.FileInfo.file_version())
                if vinfo_ver != "0.0.0.0":
                    return vinfo_ver

        #second method just incase

        return full_module_name_parts[len(full_module_name_parts) - 2]

    def bytes_to_address(self, bytes):
        block_hex_str = "".join("{:02X}".format(ord(c)) for c in reversed(bytes))
        return int(block_hex_str, 16)

    def get_hooks(self, proc, module, module_group):
        """Enumerate IAT, EAT, Inline hooks, Chromium-based SSL VMT hooks, Win/Qbot SSL hooks;

        @param addr_space: a process AS

        @param module: an _LDR_DATA_TABLE_ENTRY for the module being
        checked for hooks.

        @param module_group: a ModuleGroup instance for the process.
        """
        addr_space = proc.get_process_address_space()

        bits32 = proc.IsWow64 or addr_space.profile.metadata.get("memory_model", "32bit") == "32bit"

        if bits32:
            decode_bits = distorm3.Decode32Bits
        else:
            decode_bits = distorm3.Decode64Bits

        # We start with the module base name. If that's not available,
        # trim the full name down to its base name.
        module_name = (str(module.BaseDllName or '') or ntpath.basename(str(module.FullDllName or '')))
        # Lowercase for string matching
        module_name = module_name.lower()
        imports, exports = self.gather_stuff(addr_space, module)

        for dll, functions in imports.items():
            valid_owners = module_group.mod_name.get(dll, [])
            if not valid_owners:
                #PK print("get_hooks: Cannot find any modules named {0}".format(dll))
                continue

            for (_, f, n) in functions:

                if not f:
                    #PK print("get_hooks: IAT function {0} is paged or ordinal".format(n or ''))
                    continue

                if not addr_space.is_valid_address(f):
                    #PK print("get_hooks: not valid address 0x%X"%(f))
                    continue

                function_owner = module_group.find_module(f)

                if function_owner not in valid_owners:
                    jump_bytes = addr_space.zread(f, 6)
                    jump_str = "".join("{:02x}".format(ord(c)) for c in jump_bytes)
                    if jump_str == "ff2500000000":
                        jump_addr_bytes = addr_space.zread(f+6, 8)
                        jump_addr_str = "".join("{:02x}".format(ord(c)) for c in reversed(jump_addr_bytes))
                        print "    " + jump_addr_str
                        f = int(jump_addr_str,16)

                    #PK print("get_hooks: starting the hook search %s named %s"%(function_owner, n))
                    hook = Hook(hook_type = HOOKTYPE_IAT,
                                function_name = n or '',
                                hook_address = f,
                                hook_module = function_owner,
                                victim_module = dll, # only for IAT hooks
                                )
                    # Add the rootkit code
                    hook.add_hop_chunk(f, addr_space.zread(f, 24))
                    yield hook

        #PK print("get_hooks: starting in exports")
        for _, f, n in exports:
            if not f:
                #PK print("get_hooks: EAT function {0} is paged".format(n or ''))
                continue

            function_address = f

            if not addr_space.is_valid_address(function_address):
                continue

            # Get the module containing the function
            function_owner = module_group.find_module(function_address)

            # This is a check for EAT hooks
            if function_owner != module:
                jump_bytes = addr_space.zread(function_address, 6)
                jump_str = "".join("{:02x}".format(ord(c)) for c in jump_bytes)
                if jump_str == "ff2500000000":
                    jump_addr_bytes = addr_space.zread(function_address+6, 8)
                    function_address = self.bytes_to_address(jump_addr_bytes)


                hook = Hook(hook_type = HOOKTYPE_EAT,
                            function_name = n or '',
                            hook_address = function_address,
                            hook_module = function_owner,
                            )
                hook.add_hop_chunk(function_address, addr_space.zread(function_address, 24))
                yield hook

                # No need to check for inline hooks if EAT is hooked
                continue


            ret = self.check_inline(function_address, addr_space, module.DllBase, module.DllBase + module.SizeOfImage, mode = decode_bits)

            if ret == None:
                print("get_hooks: Cannot analyze {0}".format(n or ''))
                continue

            (hooked, data, dest_addr) = ret

            if not hooked:
                continue

            if not addr_space.is_valid_address(dest_addr):
                continue

            function_owner = module_group.find_module(dest_addr)
            if function_owner != module:
                jump_bytes = addr_space.zread(dest_addr, 6)
                jump_str = "".join("{:02x}".format(ord(c)) for c in jump_bytes)
                if jump_str == "ff2500000000":
                    jump_addr_bytes = addr_space.zread(dest_addr+6, 8)
                    dest_addr = self.bytes_to_address(jump_addr_bytes)


                hook = Hook(hook_type = HOOKTYPE_INLINE,
                            function_name = n or '',
                            function_address = function_address,
                            hook_address = dest_addr,
                            hook_module = function_owner,
                            victim_module = module,
                            decode_bits = decode_bits,
                            )
                # Add the function prologue
                hook.add_hop_chunk(function_address, data)
                # Add the first redirection
                hook.add_hop_chunk(dest_addr, addr_space.zread(dest_addr, 24))
                yield hook

        if "chrome.dll" not in module_name:
            return

        chrome_version = self.get_file_version(module, addr_space)
        if chrome_version:
            print("    chrome.dll version: {0}".format(chrome_version))
            ver_major = chrome_version.split(".")[0]
            print("    chrome.dll major version: {0}".format(ver_major))

            if int(ver_major) < 64:
               print "Error: SSL VMT table lookup no longer supported! Please use the old version"
               return

            if decode_bits == 1:
                offsets_write = CHROME_SSL_WRITE_OFFSETS_X86
                offsets_read = CHROME_SSL_READ_OFFSETS_X86
                offsets_other = CHROME_SSL_OTHER_OFFSETS_X86
            else:
                offsets_write = CHROME_SSL_WRITE_OFFSETS_X64
                offsets_read = CHROME_SSL_READ_OFFSETS_X64
                offsets_other = CHROME_SSL_OTHER_OFFSETS_X64

            if chrome_version in offsets_read:
                for offset in offsets_read[chrome_version]:
                    function_address = module.DllBase + offset

                    ret = self.check_inline(function_address, addr_space, module.DllBase, module.DllBase + module.SizeOfImage, mode = decode_bits)
                    if ret == None:
                        #PK print("get_hooks: Cannot analyze {0}".format(n or ''))
                        continue

                    (hooked, data, dest_addr) = ret

                    if not hooked:
                        continue

                    if not addr_space.is_valid_address(dest_addr):
                        continue

                    function_owner = module_group.find_module(dest_addr)
                    if function_owner != module:
                        jump_bytes = addr_space.zread(dest_addr, 6)
                        jump_str = "".join("{:02x}".format(ord(c)) for c in jump_bytes)
                        if jump_str == "ff2500000000":
                            jump_addr_bytes = addr_space.zread(dest_addr+6, 8)
                            dest_addr = self.bytes_to_address(jump_addr_bytes)

                        hook = Hook(hook_type = HOOKTYPE_INLINE_CHROME_V64_SSL_READ,
                                    function_name = hex(function_address) or '',
                                    function_address = function_address,
                                    hook_address = dest_addr,
                                    hook_module = function_owner,
                                    victim_module = module,
                                    decode_bits = decode_bits,
                                    )
                        # Add the function prologue
                        hook.add_hop_chunk(function_address, data)
                        # Add the first redirection
                        hook.add_hop_chunk(dest_addr, addr_space.zread(dest_addr, 24))
                        yield hook

            if chrome_version in offsets_write:
                for offset in offsets_write[chrome_version]:
                    function_address = module.DllBase + offset

                    ret = self.check_inline(function_address, addr_space, module.DllBase, module.DllBase + module.SizeOfImage, mode = decode_bits)
                    if ret == None:
                        #PK print("get_hooks: Cannot analyze {0}".format(n or ''))
                        continue

                    (hooked, data, dest_addr) = ret

                    if not hooked:
                        continue

                    if not addr_space.is_valid_address(dest_addr):
                        continue

                    function_owner = module_group.find_module(dest_addr)
                    if function_owner != module:
                        jump_bytes = addr_space.zread(dest_addr, 6)
                        jump_str = "".join("{:02x}".format(ord(c)) for c in jump_bytes)
                        if jump_str == "ff2500000000":
                            jump_addr_bytes = addr_space.zread(dest_addr+6, 8)
                            dest_addr = self.bytes_to_address(jump_addr_bytes)

                        hook = Hook(hook_type = HOOKTYPE_INLINE_CHROME_V64_SSL_WRITE,
                                    function_name = hex(function_address) or '',
                                    function_address = function_address,
                                    hook_address = dest_addr,
                                    hook_module = function_owner,
                                    victim_module = module,
                                    decode_bits = decode_bits,
                                    )
                        # Add the function prologue
                        hook.add_hop_chunk(function_address, data)
                        # Add the first redirection
                        hook.add_hop_chunk(dest_addr, addr_space.zread(dest_addr, 24))
                        yield hook

            if chrome_version in offsets_other:
                for offset in offsets_other[chrome_version]:
                    function_address = module.DllBase + offset

                    ret = self.check_inline(function_address, addr_space, module.DllBase, module.DllBase + module.SizeOfImage, mode = decode_bits)
                    if ret == None:
                        #PK print("get_hooks: Cannot analyze {0}".format(n or ''))
                        continue

                    (hooked, data, dest_addr) = ret

                    if not hooked:
                        continue

                    if not addr_space.is_valid_address(dest_addr):
                        continue

                    function_owner = module_group.find_module(dest_addr)
                    if function_owner != module:
                        jump_bytes = addr_space.zread(dest_addr, 6)
                        jump_str = "".join("{:02x}".format(ord(c)) for c in jump_bytes)
                        if jump_str == "ff2500000000":
                            jump_addr_bytes = addr_space.zread(dest_addr+6, 8)
                            dest_addr = self.bytes_to_address(jump_addr_bytes)

                        hook = Hook(hook_type = HOOKTYPE_INLINE_CHROME_V64_SSL_OTHER,
                                    function_name = hex(function_address) or '',
                                    function_address = function_address,
                                    hook_address = dest_addr,
                                    hook_module = function_owner,
                                    victim_module = module,
                                    decode_bits = decode_bits,
                                    )
                        # Add the function prologue
                        hook.add_hop_chunk(function_address, data)
                        # Add the first redirection
                        hook.add_hop_chunk(dest_addr, addr_space.zread(dest_addr, 24))
                        yield hook


    def get_wow64_modules(self, proc):
        mapped_files = {}
        for vad, address_space in proc.get_vads(vad_filter = proc._mapped_file_filter):
            # Note this is a lot faster than acquiring the full
            # vad region and then checking the first two bytes.
            dos_header =  obj.Object("_IMAGE_DOS_HEADER", offset = vad.Start, vm = address_space)
            if dos_header.e_magic != 0x5A4D:
                continue
            if dos_header.get_nt_header().OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR32_MAGIC:
                continue

            mapped_files[int(vad.Start)] = str(vad.FileObject.FileName or '')

        # For each base address with a mapped file, print info on
        # the other PEB lists to spot discrepancies.
        for base in mapped_files.keys():
            yield ([vad_ck().get_vad_base(proc, base),
                            vad_ck().get_vad_end(proc, base),
                            str(mapped_files[base])])
    def get_wow64_hooks(self, process):
        decode_bits = distorm3.Decode32Bits

        modules = self.get_wow64_modules(process)
        for module_start, module_end, module_path in modules:
            if "chrome.dll" not in module_path:
                continue

            print module_path

    def get_modules_wow64(self, proc):
        addr_space = proc.get_process_address_space()
        addr_space.profile.add_types(wow64_types)
        # PEB32 is always located one page above PEB64 in wow64 process
        peb32 = obj.Object("_PEB32", offset = proc.Peb._vol_offset - 0x1000, vm = addr_space)
        ldr = obj.Object("_PEB_LDR_DATA32", offset = peb32.Ldr, vm = addr_space)
        first_entry = ldr.InLoadOrderModuleList
        curr_entry = first_entry
        while True:
            mod = obj.Object("_LDR_DATA_TABLE_ENTRY32", offset = curr_entry._vol_offset, vm = addr_space)
            yield mod

            curr_entry = curr_entry.Flink
            if curr_entry == first_entry:
                break

    def calculate(self):

        addr_space = utils.load_as(self._config)
        ## prerequisities
        if not has_distorm3:
            debug.error("Install distorm3 code.google.com/p/distorm/")
        if not has_yara:
            debug.error("Please install Yara from https://plusvic.github.io/yara/")

        for proc in self.filter_tasks(tasks.pslist(addr_space)):
            process_space = proc.get_process_address_space()
            if not process_space:
                print("Cannot acquire process AS for {0} ({1})".format(proc.ImageFileName, proc.UniqueProcessId))
                continue
            #PK process_space.profile.add_types(wow64_types)
            process_space.profile.object_classes.update({'_UNICODE_STRING32': _UNICODE_STRING32,
                                                         '_LDR_DATA_TABLE_ENTRY32' : _LDR_DATA_TABLE_ENTRY32,
                                                         '_IMAGE_IMPORT_DESCRIPTOR32' : _IMAGE_IMPORT_DESCRIPTOR32})
            i = 0
            if proc.IsWow64:
                module_group = ModuleGroup(self.get_modules_wow64(proc))
            else:
                module_group = ModuleGroup(proc.get_load_modules())
            for dll in module_group.mods:
                if not process_space.is_valid_address(dll.DllBase):
                    continue

                dll_name = str(dll.BaseDllName or '').lower()

                if (dll_name not in self.critical_dlls and dll.DllBase != proc.Peb.ImageBaseAddress):
                    #PK print("Skipping non-critical dll {0} at {1:#x}".format( dll_name, dll.DllBase))
                    continue

                for hook in self.get_hooks(proc, dll, module_group):
                    if self.whitelist(hook.hook_type, str(proc.ImageFileName), hook.VictimModule, hook.HookModule, hook.Function):
                        continue

                    print "dll: %s"%(dll.BaseDllName)
                    yield proc, dll, hook


    def unified_output(self, data):
        return TreeGrid([("HookType", str),
                       ("Process", str),
                       ("PID", int),
                       ("VictimModule", str),
                       ("VictimModBase", Address),
                       ("VictimModSize", int),
                       ("Function", str),
                       ("HookAddress", Address),
                       ("HookModBase", Address),
                       ("HookModule", str),
                       ("DataAddress", Address),
                       ("Data", Bytes)],
                        self.generator(data))

    def generator(self, data):

        for process, module, hook in data:
            procname = "N/A"
            pid = -1
            addr_base = 0

            for n, info in enumerate(hook.disassembled_hops):
                (address, data) = info
                addr_base = vad_ck().get_vad_base(process, address)
                procname = str(process.ImageFileName)
                pid = int(process.UniqueProcessId)

                yield (0, [str(hook.Type),
                    procname,
                    pid,
                    str(module.BaseDllName or '') or ntpath.basename(str(module.FullDllName or '')),
                    Address(module.DllBase),
                    module.DllBase + module.SizeOfImage,
                    str(hook.Detail),
                    Address(hook.hook_address),
                    Address(addr_base),
                    str(hook.HookModule),
                    Address(address),
                    Bytes(data)])


    def render_text(self, outfd, data):

        for process, module, hook in data:

            outfd.write("*" * 72 + "\n")
            outfd.write("Hook type: {0}\n".format(hook.Type))
            IsProcWow64 = process.IsWow64
            outfd.write('Process: {0} ({1}) ({2})\n'.format(
                process.UniqueProcessId, process.ImageFileName, "Wow64" if IsProcWow64 else "bitness as the image"))

            outfd.write("Victim module: {0} ({1:#x} - {2:#x})\n".format(
                str(module.BaseDllName or '') or ntpath.basename(str(module.FullDllName or '')),
                module.DllBase, module.DllBase + module.SizeOfImage))

            outfd.write("Function: {0}\n".format(hook.Detail))
            outfd.write("Hook address: {0:#x}\n".format(hook.hook_address))

            hook_mod_base = vad_ck().get_vad_base(process, hook.hook_address)
            hook_mod_end =  vad_ck().get_vad_end(process, hook.hook_address)
            if hook_mod_end != None:
                hook_mod_size = hook_mod_end - hook_mod_base
            else:
                hook_mod_size= 0x0

            outfd.write("Hooking module base: {0:#x}\n\n".format(hook_mod_base))
            outfd.write("Hooking module: {0}\n\n".format(hook.HookModule))

            if self._config.DUMP_DIR != None:
                if not os.path.isdir(self._config.DUMP_DIR):
                    debug.error(self._config.DUMP_DIR + " is not a directory")
                else:
                    proc_space = process.get_process_address_space()

                    if not proc_space.is_valid_address(hook_mod_base):
                        print "Error: DllBase is paged"
                    else:
                      process_offset = proc_space.vtop(process.obj_offset)
                      dump_file = "module.{0}.{1:x}.{2:x}.dll".format(process.UniqueProcessId, process_offset, hook_mod_base)
                      self.dump_pe(proc_space, hook_mod_base, dump_file)

            for n, info in enumerate(hook.disassembled_hops):
                (address, data) = info
                s = ["{0:#x} {1:<16} {2}".format(o, h, i)
                        for o, i, h in
                        malfind.Disassemble(data, int(address), bits = "32bit" if hook.decode_bits == distorm3.Decode32Bits else "64bit")
                    ]
                outfd.write("Disassembly({0}):\n{1}".format(n, "\n".join(s)))
                outfd.write("\n\n")
