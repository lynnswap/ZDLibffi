#include <ffi.h>
#include <stdint.h>
#include <stdio.h>

static int32_t sum(int32_t a, int32_t b) { return a + b; }

typedef struct { double scale; int64_t words[4]; } Large;
static Large transform(Large value, int32_t increment) {
    value.scale *= 2;
    for (int i = 0; i < 4; ++i) value.words[i] += increment;
    return value;
}

static void closure_sum(ffi_cif *cif, void *result, void **arguments, void *context) {
    (void)cif;
    *(ffi_sarg *)result = sum(*(int32_t *)arguments[0], *(int32_t *)arguments[1]) + *(int32_t *)context;
}


/* A NULL result means success. Callable from an isolated device test host. */
const char *ZDLibffiPointerAuthenticationTests(void) {
    ffi_cif scalar;
    ffi_type *integers[] = { &ffi_type_sint32, &ffi_type_sint32 };
    if (ffi_prep_cif(&scalar, FFI_DEFAULT_ABI, 2, &ffi_type_sint32, integers) != FFI_OK)
        return "scalar cif";
    int32_t a = 20, b = 22;
    void *arguments[] = { &a, &b };
    ffi_sarg result = 0;
    ffi_call(&scalar, FFI_FN(sum), &result, arguments);
    if (result != sum(a, b)) return "signed scalar call";

    ffi_type *fields[] = { &ffi_type_double, &ffi_type_sint64, &ffi_type_sint64,
                          &ffi_type_sint64, &ffi_type_sint64, NULL };
    ffi_type large = { .type = FFI_TYPE_STRUCT, .elements = fields };
    ffi_type *types[] = { &large, &ffi_type_sint32 };
    ffi_cif aggregate;
    if (ffi_prep_cif(&aggregate, FFI_DEFAULT_ABI, 2, &large, types) != FFI_OK)
        return "aggregate cif";
    Large input = { 1.5, { 1, 2, 3, 4 } }, output = {0};
    int32_t increment = 38;
    void *values[] = { &input, &increment };
    ffi_call(&aggregate, FFI_FN(transform), &output, values);
    Large expected = transform(input, increment);
    if (output.scale != expected.scale) return "aggregate floating-point result";
    for (int i = 0; i < 4; ++i)
        if (output.words[i] != expected.words[i]) return "aggregate indirect result";

    void *code = NULL;
    ffi_closure *closure = ffi_closure_alloc(sizeof(ffi_closure), &code);
    if (!closure) return "closure allocation";
    int32_t context = 7;
    if (ffi_prep_closure_loc(closure, &scalar, closure_sum, &context, code) != FFI_OK) {
        ffi_closure_free(closure);
        return "closure preparation";
    }
    int32_t (*callback)(int32_t, int32_t) = (int32_t (*)(int32_t, int32_t))code;
    int32_t callback_result = callback(a, b);
    ffi_closure_free(closure);
    if (callback_result != sum(a, b) + context) return "signed closure call";
    return NULL;
}

#ifndef ZD_TEST_NO_MAIN
int main(void) {
    const char *failure = ZDLibffiPointerAuthenticationTests();
    if (failure) { fprintf(stderr, "%s\n", failure); return 1; }
    puts("libffi scalar, aggregate, and closure calls passed");
    return 0;
}
#endif
