#include <dlfcn.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    const char *library = argc > 1 ? argv[1] : "./libPPPP_API.so";

    printf("phase3_probe=PPPP_GetAPIVersion\n");
    printf("library=%s\n", library);

    dlerror();
    void *handle = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        fprintf(stderr, "dlopen_error=%s\n", dlerror());
        return 20;
    }

    dlerror();
    void *symbol = dlsym(handle, "PPPP_GetAPIVersion");
    const char *error = dlerror();
    if (error != NULL || symbol == NULL) {
        fprintf(stderr, "dlsym_error=%s\n", error != NULL ? error : "symbol not found");
        dlclose(handle);
        return 21;
    }

    int32_t (*get_api_version)(void) = (int32_t (*)(void))symbol;
    int32_t version = get_api_version();

    printf("PPPP_GetAPIVersion_signed=%" PRId32 "\n", version);
    printf("PPPP_GetAPIVersion_hex=0x%08" PRIX32 "\n", (uint32_t)version);

    dlclose(handle);
    return 0;
}
