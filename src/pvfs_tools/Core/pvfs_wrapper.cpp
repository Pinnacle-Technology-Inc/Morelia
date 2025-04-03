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

// Add wrapper for C struct
struct CWrapper {
    pvfs::C c;
};

// Add test_modify_header function
__declspec(dllexport) void test_modify_header_wrapper(CWrapper* header) {
    if (!header) return;
    pvfs::test_modify_header(header->c);
}

// Basic VFS operations
__declspec(dllexport) PvfsFileWrapper* create_vfs(uint32_t block_size) {
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

__declspec(dllexport) void delete_vfs(PvfsFileWrapper* vfs) {
    if (vfs) {
        delete vfs;
    }
}

__declspec(dllexport) PvfsFileWrapper* open_vfs(const char* filename) {
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

__declspec(dllexport) PvfsFileHandleWrapper* create_file(PvfsFileWrapper* vfs, const char* filename) {
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

__declspec(dllexport) PvfsFileHandleWrapper* open_file(PvfsFileWrapper* vfs, const char* filename) {
    if (!vfs || !vfs->ptr) return nullptr;
    auto handle = new PvfsFileHandleWrapper();
    handle->ptr = std::make_shared<pvfs::PvfsFileHandle>();
    return handle;
}

__declspec(dllexport) int32_t write_file(PvfsFileHandleWrapper* handle, const uint8_t* buffer, uint32_t size) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_write(handle->ptr, buffer, size);
}

__declspec(dllexport) int32_t read_file(PvfsFileHandleWrapper* handle, uint8_t* buffer, uint32_t size) {
    if (!handle || !handle->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_read(handle->ptr, buffer, size);
}

__declspec(dllexport) void close_file(PvfsFileHandleWrapper* handle) {
    if (handle) {
        delete handle;
    }
}

__declspec(dllexport) int32_t pvfs_close(int32_t fd) {
    return pvfs::PVFS_close(fd);
}

// String vector operations
__declspec(dllexport) StringVectorWrapper* create_string_vector() {
    auto wrapper = new StringVectorWrapper();
    wrapper->strings = nullptr;
    wrapper->size = 0;
    return wrapper;
}

__declspec(dllexport) void delete_string_vector(StringVectorWrapper* vec) {
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

__declspec(dllexport) const char* get_string_at(StringVectorWrapper* vec, size_t index) {
    if (!vec || !vec->strings || index >= vec->size) return nullptr;
    return vec->strings[index];
}

__declspec(dllexport) size_t get_string_vector_size(StringVectorWrapper* vec) {
    if (!vec) return 0;
    return vec->size;
}

// File operations
__declspec(dllexport) int32_t get_channel_list(PvfsFileWrapper* vfs, StringVectorWrapper* names) {
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
                strcpy_s(names->strings[i], str.length() + 1, str.c_str());
            }
        }
        return result;
    } catch (const std::exception&) {
        return pvfs::PVFS_ERROR;
    } catch (...) {
        return pvfs::PVFS_ERROR;
    }
}

__declspec(dllexport) int32_t get_file_list(PvfsFileWrapper* vfs, StringVectorWrapper* names) {
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
                strcpy_s(names->strings[i], str.length() + 1, str.c_str());
            }
        }
        return result;
    } catch (const std::exception&) {
        return pvfs::PVFS_ERROR;
    } catch (...) {
        return pvfs::PVFS_ERROR;
    }
}

__declspec(dllexport) int32_t extract(PvfsFileWrapper* vfs, const char* in_file, const char* out_file) {
    if (!vfs || !vfs->ptr) return pvfs::PVFS_ARG_NULL;
    return pvfs::PVFS_extract(vfs->ptr, in_file, out_file);
}

// Index file operations
__declspec(dllexport) int32_t read_index_file_header(PvfsFileHandleWrapper* handle, PvfsIndexHeaderWrapper* header) {
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

__declspec(dllexport) int32_t write_index_file_header(PvfsFileHandleWrapper* handle, PvfsIndexHeaderWrapper* header) {
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

__declspec(dllexport) PvfsFileHandleWrapper* open_data_channel(PvfsFileWrapper* vfs, const char* channel_name) {
    if (!vfs || !vfs->ptr) return nullptr;
    auto handle = new PvfsFileHandleWrapper();
    handle->ptr = std::make_shared<pvfs::PvfsFileHandle>();
    return handle;
}

// HighTime operations
__declspec(dllexport) PvfsHighTimeWrapper* create_high_time(int64_t seconds, double subseconds) {
    auto wrapper = new PvfsHighTimeWrapper();
    wrapper->time = pvfs::HighTime(seconds, subseconds);
    return wrapper;
}

__declspec(dllexport) void delete_high_time(PvfsHighTimeWrapper* time) {
    if (time) {
        delete time;
    }
}

__declspec(dllexport) int64_t get_high_time_seconds(PvfsHighTimeWrapper* time) {
    if (!time) return 0;
    return time->time.seconds;
}

__declspec(dllexport) double get_high_time_subseconds(PvfsHighTimeWrapper* time) {
    if (!time) return 0.0;
    return time->time.subSeconds;
}

// Lock operations
__declspec(dllexport) void lock_vfs(PvfsFileWrapper* vfs) {
    if (!vfs || !vfs->ptr) return;
    pvfs::PVFS_lock(vfs->ptr);
}

__declspec(dllexport) void unlock_vfs(PvfsFileWrapper* vfs) {
    if (!vfs || !vfs->ptr) return;
    pvfs::PVFS_unlock(vfs->ptr);
}

} 