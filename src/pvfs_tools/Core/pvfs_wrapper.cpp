/*
Build Instructions:
1. Ensure pvfs.dll is in the source directory
2. Create and enter build directory:
   mkdir build
   cd build
3. Configure with CMake:
   cmake -DCMAKE_BUILD_TYPE=Release ..
4. Build:
   cmake --build . --config Release
5. Copy pvfs_wrapper.dll to your test directory
*/

#include "Pvfs.h"
#include <cstdint>
#include <vector>
#include <string>
#include <iostream>
#include <fstream>
#include <memory>
#include <cstring>

#ifdef _WIN32
    #define WRAPPER_DLL_EXPORT __declspec(dllexport)
#else
    #define WRAPPER_DLL_EXPORT __attribute__((visibility("default")))
#endif

extern "C" {

// Wrapper structures for C++ objects
struct PvfsFileWrapper {
    std::shared_ptr<pvfs::PvfsFile> ptr;  // Store shared_ptr directly
};

struct PvfsFileHandleWrapper {
    std::shared_ptr<pvfs::PvfsFileHandle> ptr;  // Store shared_ptr directly
};

struct StringVectorWrapper {
    char** strings;  // Array of C-style strings
    size_t size;     // Number of strings
};

struct PvfsFileEntryWrapper {
    int64_t startBlock;
    int64_t size;
    char filename[256];
};

struct PvfsLocationMapWrapper {
    int64_t startBlock;
    int64_t size;
    char location[256];
};

struct PvfsFileVersionWrapper {
    int32_t version;
    int64_t timestamp;
    char comment[256];
};

struct PvfsBlockWrapper {
    int64_t offset;
    int64_t size;
    int32_t type;
};

struct PvfsBlockDataWrapper {
    int64_t offset;
    int64_t size;
    char* data;
};

struct PvfsBlockTreeWrapper {
    int64_t offset;
    int64_t size;
    int32_t depth;
};

struct PvfsBlockFileWrapper {
    int64_t offset;
    int64_t size;
    char filename[256];
};

struct PvfsIndexHeaderWrapper {
    int32_t magicNumber;
    int32_t version;
    int32_t dataType;
    double datarate;
    pvfs::HighTime startTime;
    pvfs::HighTime endTime;
};

struct PvfsHighTimeWrapper {
    pvfs::HighTime time;
};

// Basic VFS operations
WRAPPER_DLL_EXPORT PvfsFileWrapper* create_vfs(uint32_t block_size) {
    auto wrapper = new PvfsFileWrapper();
    // Create a temporary file with the specified block size
    std::string temp_filename = "temp.vfs";
    wrapper->ptr = pvfs::PVFS_create_size(temp_filename.c_str(), block_size);
    if (!wrapper->ptr) {
        delete wrapper;
        return nullptr;
    }
    return wrapper;
}

WRAPPER_DLL_EXPORT void delete_vfs(PvfsFileWrapper* vfs) {
    if (vfs) {
        delete vfs;
    }
}

WRAPPER_DLL_EXPORT PvfsFileWrapper* open_vfs(const char* filename) {
    try {
        // Check if file exists
        std::ifstream file(filename);
        if (!file.good()) {
            return nullptr;
        }
        file.close();

        // Create a new VFS instance
        PvfsFileWrapper* wrapper = new PvfsFileWrapper();
        if (!wrapper) {
            return nullptr;
        }

        // Try to open the VFS
        wrapper->ptr = pvfs::PVFS_open(filename);
        if (!wrapper->ptr) {
            delete wrapper;
            return nullptr;
        }

        return wrapper;
    } catch (const std::exception&) {
        return nullptr;
    } catch (...) {
        return nullptr;
    }
}

WRAPPER_DLL_EXPORT PvfsFileHandleWrapper* create_file(PvfsFileWrapper* vfs, const char* filename) {
    if (!vfs || !vfs->ptr) return nullptr;
    auto handle = new PvfsFileHandleWrapper();
    int32_t result = pvfs::PVFS_add(vfs->ptr, filename, filename);
    if (result != 0) {
        delete handle;
        return nullptr;
    }
    handle->ptr = std::make_shared<pvfs::PvfsFileHandle>();
    return handle;
}

WRAPPER_DLL_EXPORT PvfsFileHandleWrapper* open_file(PvfsFileWrapper* vfs, const char* filename) {
    if (!vfs || !vfs->ptr) return nullptr;
    auto handle = new PvfsFileHandleWrapper();
    handle->ptr = pvfs::PVFS_fopen(vfs->ptr, filename);
    if (!handle->ptr) {
        delete handle;
        return nullptr;
    }
    return handle;
}

WRAPPER_DLL_EXPORT int32_t write_file(PvfsFileHandleWrapper* handle, const uint8_t* buffer, uint32_t size) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write(handle->ptr, buffer, size);
}

WRAPPER_DLL_EXPORT int32_t read_file(PvfsFileHandleWrapper* handle, uint8_t* buffer, uint32_t size) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read(handle->ptr, buffer, size);
}

WRAPPER_DLL_EXPORT void close_file(PvfsFileHandleWrapper* handle) {
    if (handle) {
        delete handle;
    }
}

WRAPPER_DLL_EXPORT int32_t pvfs_close(int32_t fd) {
    return pvfs::PVFS_close(fd);
}

// String vector operations
WRAPPER_DLL_EXPORT StringVectorWrapper* create_string_vector() {
    auto wrapper = new StringVectorWrapper();
    wrapper->strings = nullptr;
    wrapper->size = 0;
    return wrapper;
}

WRAPPER_DLL_EXPORT void delete_string_vector(StringVectorWrapper* vec) {
    if (vec) {
        if (vec->strings) {
            for (size_t i = 0; i < vec->size; i++) {
                delete[] vec->strings[i];
            }
            delete[] vec->strings;
        }
        delete vec;
    }
}

WRAPPER_DLL_EXPORT const char* get_string_at(StringVectorWrapper* vec, size_t index) {
    if (!vec || !vec->strings || index >= vec->size) return nullptr;
    return vec->strings[index];
}

WRAPPER_DLL_EXPORT size_t get_string_vector_size(StringVectorWrapper* vec) {
    if (!vec) return 0;
    return vec->size;
}

// File operations
WRAPPER_DLL_EXPORT int32_t get_channel_list(PvfsFileWrapper* vfs, StringVectorWrapper* names) {
    try {
        if (!vfs || !vfs->ptr || !names) {
            return pvfs::PVFS_ARG_NULL;
        }
        
        // Get the channel list into a C++ vector
        std::vector<std::string> channel_names;
        int32_t result = pvfs::PVFS_get_channel_list(vfs->ptr, channel_names);
        
        if (result == 0) {
            // Convert C++ vector to C-style array
            names->size = channel_names.size();
            names->strings = new char*[names->size];
            
            for (size_t i = 0; i < names->size; i++) {
                const std::string& str = channel_names[i];
                names->strings[i] = new char[str.length() + 1];
                strncpy(names->strings[i], str.c_str(), str.length() + 1 );
            }
        }
        return result;
    } catch (const std::exception&) {
        return pvfs::PVFS_ERROR;
    } catch (...) {
        return pvfs::PVFS_ERROR;
    }
}

WRAPPER_DLL_EXPORT int32_t get_file_list(PvfsFileWrapper* vfs, StringVectorWrapper* names) {
    try {
        if (!vfs || !vfs->ptr || !names) {
            return pvfs::PVFS_ARG_NULL;
        }
        
        // Get the file list into a C++ vector
        std::vector<std::string> file_names;
        int32_t result = pvfs::PVFS_get_file_list(vfs->ptr, file_names);
        
        if (result == 0) {
            // Convert C++ vector to C-style array
            names->size = file_names.size();
            names->strings = new char*[names->size];
            
            for (size_t i = 0; i < names->size; i++) {
                const std::string& str = file_names[i];
                names->strings[i] = new char[str.length() + 1];
                std::strncpy(names->strings[i],  str.c_str(), str.length() + 1);
            }
        }
        return result;
    } catch (const std::exception&) {
        return pvfs::PVFS_ERROR;
    } catch (...) {
        return pvfs::PVFS_ERROR;
    }
}

WRAPPER_DLL_EXPORT int32_t extract(PvfsFileWrapper* vfs, const char* in_file, const char* out_file) {
    if (!vfs || !vfs->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_extract(vfs->ptr, in_file, out_file);
}

// Index file operations
WRAPPER_DLL_EXPORT int32_t read_index_file_header(PvfsFileHandleWrapper* handle, PvfsIndexHeaderWrapper* header) {
    if (!handle || !handle->ptr || !header) return pvfs::PVFS_ARG_NULL;
    pvfs::PvfsIndexHeader index_header;
    int32_t result = pvfs::PVFS_read_index_file_header(handle->ptr, index_header);
    if (result == 0) {
        header->magicNumber = index_header.magicNumber;
        header->version = index_header.version;
        header->dataType = index_header.dataType;
        header->datarate = index_header.datarate;
        header->startTime = index_header.startTime;
        header->endTime = index_header.endTime;
    }
    return result;
}

WRAPPER_DLL_EXPORT int32_t write_index_file_header(PvfsFileHandleWrapper* handle, PvfsIndexHeaderWrapper* header) {
    if (!handle || !handle->ptr || !header) return pvfs::PVFS_ARG_NULL;
    pvfs::PvfsIndexHeader index_header;
    index_header.magicNumber = header->magicNumber;
    index_header.version = header->version;
    index_header.dataType = header->dataType;
    index_header.datarate = header->datarate;
    index_header.startTime = header->startTime;
    index_header.endTime = header->endTime;
    return pvfs::PVFS_write_index_file_header(handle->ptr, index_header);
}

WRAPPER_DLL_EXPORT PvfsFileHandleWrapper* open_data_channel(PvfsFileWrapper* vfs, const char* channel_name) {
    if (!vfs || !vfs->ptr) return nullptr;
    auto handle = new PvfsFileHandleWrapper();
    handle->ptr = std::make_shared<pvfs::PvfsFileHandle>();
    return handle;
}

// HighTime operations
WRAPPER_DLL_EXPORT PvfsHighTimeWrapper* create_high_time(int64_t seconds, double subseconds) {
    auto wrapper = new PvfsHighTimeWrapper();
    wrapper->time = pvfs::HighTime(seconds, subseconds);
    return wrapper;
}

WRAPPER_DLL_EXPORT void delete_high_time(PvfsHighTimeWrapper* time) {
    if (time) {
        delete time;
    }
}

WRAPPER_DLL_EXPORT int64_t get_high_time_seconds(PvfsHighTimeWrapper* time) {
    if (!time) return 0;
    return time->time.seconds;
}

WRAPPER_DLL_EXPORT double get_high_time_subseconds(PvfsHighTimeWrapper* time) {
    if (!time) return 0.0;
    return time->time.subSeconds;
}

// Lock operations
WRAPPER_DLL_EXPORT void lock_vfs(PvfsFileWrapper* vfs) {
    if (!vfs || !vfs->ptr) return;
    pvfs::PVFS_lock(vfs->ptr);
}

WRAPPER_DLL_EXPORT void unlock_vfs(PvfsFileWrapper* vfs) {
    if (!vfs || !vfs->ptr) return;
    pvfs::PVFS_unlock(vfs->ptr);
}

// Add new file operations
WRAPPER_DLL_EXPORT int32_t pvfs_fclose(PvfsFileHandleWrapper* handle) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return static_cast<int32_t>(pvfs::PVFS_fclose(handle->ptr));
}

WRAPPER_DLL_EXPORT int32_t pvfs_flush(PvfsFileHandleWrapper* handle) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return static_cast<int32_t>(pvfs::PVFS_flush(handle->ptr));
}

WRAPPER_DLL_EXPORT PvfsFileHandleWrapper* pvfs_fcreate(PvfsFileWrapper* vfs, const char* filename) {
    if (!vfs || !vfs->ptr) return nullptr;
    auto handle = new PvfsFileHandleWrapper();
    handle->ptr = pvfs::PVFS_fcreate(vfs->ptr, filename);
    if (!handle->ptr) {
        delete handle;
        return nullptr;
    }
    return handle;
}

WRAPPER_DLL_EXPORT PvfsFileHandleWrapper* pvfs_fopen(PvfsFileWrapper* vfs, const char* filename) {
    if (!vfs || !vfs->ptr) return nullptr;
    auto handle = new PvfsFileHandleWrapper();
    handle->ptr = pvfs::PVFS_fopen(vfs->ptr, filename);
    if (!handle->ptr) {
        delete handle;
        return nullptr;
    }
    return handle;
}

WRAPPER_DLL_EXPORT int32_t pvfs_delete_file(PvfsFileWrapper* vfs, const char* filename) {
    if (!vfs || !vfs->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_delete_file(vfs->ptr, filename);
}

// Add low-level file operations
WRAPPER_DLL_EXPORT int64_t pvfs_tell(PvfsFileHandleWrapper* handle) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_tell(handle->ptr);
}

WRAPPER_DLL_EXPORT int64_t pvfs_seek(PvfsFileHandleWrapper* handle, int64_t offset) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_seek(handle->ptr, offset);
}

WRAPPER_DLL_EXPORT int32_t pvfs_write(PvfsFileHandleWrapper* handle, const uint8_t* buffer, uint32_t size) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write(handle->ptr, buffer, size);
}

WRAPPER_DLL_EXPORT int32_t pvfs_read(PvfsFileHandleWrapper* handle, uint8_t* buffer, uint32_t size) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read(handle->ptr, buffer, size);
}

// Add type-specific write functions
WRAPPER_DLL_EXPORT int64_t pvfs_write_uint8(PvfsFileHandleWrapper* handle, uint8_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write_uint8(handle->ptr->vfs->fd, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_write_sint8(PvfsFileHandleWrapper* handle, int8_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write_sint8(handle->ptr->vfs->fd, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_write_sint16(PvfsFileHandleWrapper* handle, int16_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write_sint16(handle->ptr->vfs->fd, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_write_uint16(PvfsFileHandleWrapper* handle, uint16_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write_uint16(handle->ptr->vfs->fd, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_write_sint32(PvfsFileHandleWrapper* handle, int32_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write_sint32(handle->ptr->vfs->fd, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_write_uint32(PvfsFileHandleWrapper* handle, uint32_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write_uint32(handle->ptr->vfs->fd, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_write_sint64(PvfsFileHandleWrapper* handle, int64_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write_sint64(handle->ptr->vfs->fd, value);
}

// Add type-specific read functions
WRAPPER_DLL_EXPORT int64_t pvfs_read_uint8(PvfsFileHandleWrapper* handle, uint8_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read_uint8(handle->ptr->vfs->fd, *value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_read_sint8(PvfsFileHandleWrapper* handle, int8_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read_sint8(handle->ptr->vfs->fd, *value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_read_sint16(PvfsFileHandleWrapper* handle, int16_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read_sint16(handle->ptr->vfs->fd, *value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_read_uint16(PvfsFileHandleWrapper* handle, uint16_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read_uint16(handle->ptr->vfs->fd, *value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_read_sint32(PvfsFileHandleWrapper* handle, int32_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read_sint32(handle->ptr->vfs->fd, *value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_read_uint32(PvfsFileHandleWrapper* handle, uint32_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read_uint32(handle->ptr->vfs->fd, *value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_read_sint64(PvfsFileHandleWrapper* handle, int64_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read_sint64(handle->ptr->vfs->fd, *value);
}

// Add type-specific fwrite functions
WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_uint8(PvfsFileHandleWrapper* handle, uint8_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_uint8(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_sint8(PvfsFileHandleWrapper* handle, int8_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_sint8(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_sint16(PvfsFileHandleWrapper* handle, int16_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_sint16(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_uint16(PvfsFileHandleWrapper* handle, uint16_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_uint16(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_sint32(PvfsFileHandleWrapper* handle, int32_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_sint32(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_uint32(PvfsFileHandleWrapper* handle, uint32_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_uint32(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_sint64(PvfsFileHandleWrapper* handle, int64_t value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_sint64(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_float(PvfsFileHandleWrapper* handle, float value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_float(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fwrite_double(PvfsFileHandleWrapper* handle, double value) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fwrite_double(handle->ptr, value);
}

// Add type-specific fread functions
WRAPPER_DLL_EXPORT int64_t pvfs_fread_uint8(PvfsFileHandleWrapper* handle, uint8_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_uint8(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_sint8(PvfsFileHandleWrapper* handle, int8_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_sint8(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_sint16(PvfsFileHandleWrapper* handle, int16_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_sint16(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_uint16(PvfsFileHandleWrapper* handle, uint16_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_uint16(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_sint32(PvfsFileHandleWrapper* handle, int32_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_sint32(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_uint32(PvfsFileHandleWrapper* handle, uint32_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_uint32(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_sint64(PvfsFileHandleWrapper* handle, int64_t* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_sint64(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_float(PvfsFileHandleWrapper* handle, float* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_float(handle->ptr, value);
}

WRAPPER_DLL_EXPORT int64_t pvfs_fread_double(PvfsFileHandleWrapper* handle, double* value) {
    if (!handle || !handle->ptr || !value) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_fread_double(handle->ptr, value);
}

WRAPPER_DLL_EXPORT PvfsFileEntryWrapper get_file_info(PvfsFileHandleWrapper* handle) 
{
    PvfsFileEntryWrapper result = {0};
    if (!handle || !handle->ptr) {
        // Either return a default-constructed result or handle the error differently.
        return result;
    }

    // Copy from the real info struct
    const auto &entry = handle->ptr->info;
    result.startBlock = entry.startBlock;
    result.size       = entry.size;

    // Copy the filename (up to 256 bytes in PvfsFileEntryWrapper)
    memcpy(result.filename, entry.filename, sizeof(result.filename));
    return result;
}

WRAPPER_DLL_EXPORT void pvfs_close_file_handle(PvfsFileHandleWrapper* handle) {
    if (handle && handle->ptr) {
        handle->ptr.reset();  // Force shared_ptr to release
    }
}

WRAPPER_DLL_EXPORT void pvfs_close_vfs(PvfsFileWrapper* wrapper) {
    if (wrapper && wrapper->ptr) {
        wrapper->ptr.reset();  //  release shared_ptr to PvfsFile
    }
}

} 