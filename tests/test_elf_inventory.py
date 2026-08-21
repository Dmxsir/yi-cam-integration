import struct
import unittest
from pathlib import Path

from tools.elf_inventory import inspect_elf, read_export_code


class ElfInventoryTests(unittest.TestCase):
    def test_current_pppp_library_is_aarch64_and_exports_core_api(self):
        path = Path("current-native-analysis/lib/arm64-v8a/libPPPP_API.so")
        if not path.exists():
            self.skipTest("current installed ARM64 split is not present")
        result = inspect_elf(path)
        self.assertEqual(result["architecture"], "AArch64")
        self.assertEqual(
            result["sha256"],
            "8C53F2ECC7CE6C362960AF29A5D8DE8396347A120DC10E88B24928437C4286EB",
        )
        required = {
            "PPPP_GetAPIVersion",
            "PPPP_Initialize",
            "PPPP_DeInitialize",
            "PPPP_Connect",
            "PPPP_ConnectByServer",
            "PPPP_Check",
            "PPPP_Read",
            "PPPP_Write",
            "PPPP_SendLogin",
            "PPPP_Close",
            "PPPP_ForceClose",
            "PPPP_WakeUp",
            "PPPP_WakeUp_And_Connect",
        }
        self.assertTrue(required.issubset(result["exports"]))

    def test_current_pppp_api_version_is_statically_decodable(self):
        path = Path("current-native-analysis/lib/arm64-v8a/libPPPP_API.so")
        if not path.exists():
            self.skipTest("current installed ARM64 split is not present")
        entry = read_export_code(path, "PPPP_GetAPIVersion")
        branch = struct.unpack_from("<I", entry["code"])[0]
        self.assertEqual(branch & 0x7C000000, 0x14000000)

        displacement = branch & 0x03FFFFFF
        if displacement & 0x02000000:
            displacement -= 0x04000000
        target = entry["virtual_address"] + displacement * 4
        implementation = read_export_code(path, "PPPP_Get_APIVersion")
        self.assertEqual(target, implementation["virtual_address"])

        words = struct.unpack_from("<II", implementation["code"])
        value = ((words[0] >> 5) & 0xFFFF) | (((words[1] >> 5) & 0xFFFF) << 16)
        self.assertEqual(value, 0xA2050401)


if __name__ == "__main__":
    unittest.main()
