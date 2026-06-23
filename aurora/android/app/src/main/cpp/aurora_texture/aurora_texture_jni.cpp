/*
 * Aurora Texture Engine JNI Bridge
 * =================================
 *
 * Provides native texture transcoding via Basis Universal's transcoder.
 * Converts KTX2/UASTC files to ASTC format (mobile GPU native).
 *
 * Called from AuroraTextureHelper.java during container creation.
 *
 * Phase 1 integration into GameNative.
 */

#include <jni.h>
#include <android/log.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

// Basis Universal transcoder (single-file, no external deps)
#include "basisu_transcoder.h"

#define TAG "AuroraTexture"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

static bool g_initialized = false;

// =============================================================================
// JNI functions
// =============================================================================

extern "C" {

/**
 * Initialize the Basis Universal transcoder. Must be called once before
 * any transcoding. Thread-safe (uses atomic flag internally).
 */
JNIEXPORT jboolean JNICALL
Java_com_winlator_core_AuroraTextureHelper_nativeInit(JNIEnv* env, jclass cls) {
    if (g_initialized) return JNI_TRUE;

    LOGI("Initializing Basis Universal transcoder...");
    basist::basisu_transcoder_init();
    g_initialized = true;
    LOGI("Basis Universal transcoder initialized (v%s)", BASISU_VERSION);
    return JNI_TRUE;
}

/**
 * Transcode a KTX2/UASTC file to ASTC format.
 *
 * @param inputPath Path to the .ktx2 input file
 * @param outputPath Path to write the .astc output file
 * @return true on success, false on failure
 */
JNIEXPORT jboolean JNICALL
Java_com_winlator_core_AuroraTextureHelper_nativeTranscodeKtx2ToAstc(
        JNIEnv* env, jclass cls,
        jstring inputPath, jstring outputPath) {

    if (!g_initialized) {
        LOGE("Transcoder not initialized — call nativeInit() first");
        return JNI_FALSE;
    }

    const char* inPath = env->GetStringUTFChars(inputPath, nullptr);
    const char* outPath = env->GetStringUTFChars(outputPath, nullptr);

    LOGI("Transcoding: %s -> %s", inPath, outPath);

    // Read the KTX2 file
    FILE* inFile = fopen(inPath, "rb");
    if (!inFile) {
        LOGE("Cannot open input file: %s", inPath);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    fseek(inFile, 0, SEEK_END);
    long fileSize = ftell(inFile);
    fseek(inFile, 0, SEEK_SET);

    if (fileSize <= 0) {
        LOGE("Input file is empty: %s", inPath);
        fclose(inFile);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    uint8_t* fileData = (uint8_t*)malloc(fileSize);
    if (!fileData) {
        LOGE("Cannot allocate %ld bytes for input file", fileSize);
        fclose(inFile);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    size_t bytesRead = fread(fileData, 1, fileSize, inFile);
    fclose(inFile);

    if ((long)bytesRead != fileSize) {
        LOGE("Short read: got %zu, expected %ld", bytesRead, fileSize);
        free(fileData);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    LOGI("Read %ld bytes from %s", fileSize, inPath);

    // Initialize KTX2 transcoder
    basist::ktx2_transcoder ktx2_tc;
    if (!ktx2_tc.init(fileData, fileSize)) {
        LOGE("Failed to init KTX2 transcoder — not a valid KTX2 file?");
        free(fileData);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    LOGI("KTX2 file: width=%u, height=%u, layers=%u, mips=%u, format=%u",
         ktx2_tc.get_width(), ktx2_tc.get_height(),
         ktx2_tc.get_layers(), ktx2_tc.get_levels(),
         ktx2_tc.get_format());

    // Create the basisu transcoder
    basist::basisu_transcoder transcoder;

    // Transcode to ASTC 4x4 LDR RGBA
    // For each mip level, transcode and write to output
    FILE* outFile = fopen(outPath, "wb");
    if (!outFile) {
        LOGE("Cannot open output file: %s", outPath);
        free(fileData);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    uint32_t width = ktx2_tc.get_width();
    uint32_t height = ktx2_tc.get_height();
    uint32_t levels = ktx2_tc.get_levels();

    // Write ASTC file header (16 bytes)
    // ASTC header: magic(4) + blockX(1) + blockY(1) + blockZ(1) + dimX(3) + dimY(3) + dimZ(3)
    uint8_t astcHeader[16];
    astcHeader[0] = 0x13; astcHeader[1] = 0xAB; astcHeader[2] = 0xA1; astcHeader[3] = 0x5C; // magic
    astcHeader[4] = 4;  // blockX (4x4 ASTC)
    astcHeader[5] = 4;  // blockY
    astcHeader[6] = 1;  // blockZ
    // dimX (3 bytes, little-endian)
    astcHeader[7] = width & 0xFF;
    astcHeader[8] = (width >> 8) & 0xFF;
    astcHeader[9] = (width >> 16) & 0xFF;
    // dimY (3 bytes, little-endian)
    astcHeader[10] = height & 0xFF;
    astcHeader[11] = (height >> 8) & 0xFF;
    astcHeader[12] = (height >> 16) & 0xFF;
    // dimZ (3 bytes)
    astcHeader[13] = 1;
    astcHeader[14] = 0;
    astcHeader[15] = 0;

    fwrite(astcHeader, 1, 16, outFile);

    // Transcode each mip level
    bool success = true;
    for (uint32_t level = 0; level < levels; level++) {
        uint32_t levelWidth = width >> level;
        uint32_t levelHeight = height >> level;
        if (levelWidth == 0) levelWidth = 1;
        if (levelHeight == 0) levelHeight = 1;

        // Calculate blocks needed (4x4 ASTC blocks)
        uint32_t blocksX = (levelWidth + 3) / 4;
        uint32_t blocksY = (levelHeight + 3) / 4;
        uint32_t totalBlocks = blocksX * blocksY;

        // Allocate output buffer (16 bytes per ASTC block)
        uint32_t outputSize = totalBlocks * 16;
        void* outputBuf = malloc(outputSize);
        if (!outputBuf) {
            LOGE("Cannot allocate %u bytes for ASTC output", outputSize);
            success = false;
            break;
        }

        // Transcode this level to ASTC
        bool result = ktx2_tc.transcode(
            &transcoder,
            level,              // level_index
            0,                  // layer_index
            0,                  // face_index
            outputBuf,          // pOutput_blocks
            outputSize,         // output_blocks_buf_size
            basist::transcoder_texture_format::cTFASTC_4x4_RGBA,
            0,                  // decode_flags
            1,                  // pack2
            nullptr,            // pAlpha_blocks
            0,                  // alpha_blocks_buf_size
            nullptr             // pOutput_row_pitch_in_blocks
        );

        if (!result) {
            LOGE("Transcode failed for level %u", level);
            free(outputBuf);
            success = false;
            break;
        }

        size_t written = fwrite(outputBuf, 1, outputSize, outFile);
        free(outputBuf);

        if (written != outputSize) {
            LOGE("Short write for level %u: got %zu, expected %u", level, written, outputSize);
            success = false;
            break;
        }

        LOGI("Transcoded level %u: %ux%u -> %u blocks (%u bytes)",
             level, levelWidth, levelHeight, totalBlocks, outputSize);
    }

    fclose(outFile);
    free(fileData);

    if (success) {
        LOGI("Transcode complete: %s -> %s", inPath, outPath);
    } else {
        LOGE("Transcode failed");
        // Remove partial output file
        remove(outPath);
    }

    env->ReleaseStringUTFChars(inputPath, inPath);
    env->ReleaseStringUTFChars(outputPath, outPath);

    return success ? JNI_TRUE : JNI_FALSE;
}

/**
 * Check if a file is a valid KTX2 file.
 * @param filePath Path to check
 * @return true if valid KTX2
 */
JNIEXPORT jboolean JNICALL
Java_com_winlator_core_AuroraTextureHelper_nativeIsKtx2File(
        JNIEnv* env, jclass cls, jstring filePath) {

    const char* path = env->GetStringUTFChars(filePath, nullptr);
    FILE* f = fopen(path, "rb");
    if (!f) {
        env->ReleaseStringUTFChars(filePath, path);
        return JNI_FALSE;
    }

    // KTX2 magic: 0xAB 0x4B 0x54 0x58 0x20 0x32 0x30 0xBB
    uint8_t magic[8];
    size_t read = fread(magic, 1, 8, f);
    fclose(f);
    env->ReleaseStringUTFChars(filePath, path);

    if (read != 8) return JNI_FALSE;

    static const uint8_t ktx2_magic[8] = {0xAB, 0x4B, 0x54, 0x58, 0x20, 0x32, 0x30, 0xBB};
    return (memcmp(magic, ktx2_magic, 8) == 0) ? JNI_TRUE : JNI_FALSE;
}

} // extern "C"
