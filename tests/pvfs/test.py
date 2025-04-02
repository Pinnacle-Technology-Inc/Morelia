import sys
import os
import struct

from pvfs_tools.Core.pvfs_binding import PVFSBinding

from test_pvfs import test_pvfs_data_channel
#from test_pvfs import test_pvfs_extract_database
#from test_pvfs import test_pvfs_get_channel_list
#from test_pvfs import test_pvfs_modify_header
from test_pvfs import test_pvfs_get_file_list
#from test_pvfs import test_pvfs_extract
#from test_pvfs import wrap_vp8_to_webm

# Create an instance of the Pvfs class
pvfs_instance = PVFSBinding()

# Put the path to the pvfs file 
file_path = '/mnt/e/newPython/PVFS_test/test1.pvfs'
#file_path = '/mnt/f/temp/sleep_dep.pvfs'
channel_name = "EMG2"
in_file = "Camera_video4_frames"
out_file = "/mnt/e/newPython/PVFS_test/video.vp8"
webm_file = "/mnt/e/newPython/PVFS_test/video.webm"

#test_pvfs_get_channel_list(pvfs_instance, file_path)
#test_pvfs_extract_database(pvfs_instance, file_path)
#test_pvfs_modify_header(pvfs_instance)
#test_pvfs_open_data_channel(pvfs_instance, file_path, channel_name)
test_pvfs_get_file_list(pvfs_instance, file_path)
#test_pvfs_extract(pvfs_instance, file_path, in_file, out_file)
#wrap_vp8_to_webm(out_file, webm_file)

# #vfs here represents the instance of vfs that is referenced in function 'createVFS' from Pvfs.cpp
# # This instance will have all the attributes of the struct 'PvfsFile' from Pvfs.cpp
# vfs = pvfs_instance.createVFS(Pvfs.PVFS_DEFAULT_BLOCK_SIZE)

# vfs = pvfs_instance.create_PVFS_file_structure(Pvfs.PVFS_DEFAULT_BLOCK_SIZE)

# # #doesn't return anything
# result = pvfs_instance.PVFS_file_set_blockSize(vfs,Pvfs.PVFS_DEFAULT_BLOCK_SIZE)

# block = pvfs_instance.create_PVFS_block(vfs) #returns an instance of create_PVFS_block


# # fd is an attribute to the vfs instance we created earlier. 
# file_descriptor = vfs.fd

# read_block = pvfs_instance.PVFS_read_block(file_descriptor, 0, block)


# write_block = pvfs_instance.PVFS_write_block(file_descriptor, 0, block)


# block_data = pvfs_instance.create_PVFS_block_data(vfs)
# block_tree = pvfs_instance.create_PVFS_block_tree(vfs)
# block_file = pvfs_instance.create_PVFS_block_file(vfs)


# pvfs_instance.PVFS_cast_block_to_data(block, block_data)
# pvfs_instance.PVFS_cast_block_to_tree(block, block_tree)
# pvfs_instance.PVFS_cast_block_to_file(block, block_file)
# pvfs_instance.PVFS_cast_data_to_block(block_data, block)
# pvfs_instance.PVFS_cast_tree_to_block(block_tree, block)
# pvfs_instance.PVFS_cast_file_to_block(block_file, block)

# pvfs_instance.PVFS_read_block_file(vfs, 0, block_file)
# pvfs_instance.PVFS_read_block_tree(vfs, 0, block_tree)
# pvfs_instance.PVFS_read_block_data(vfs, 0, block_data)
# pvfs_instance.PVFS_write_block_file(vfs, 0, block_file)
# pvfs_instance.PVFS_write_block_tree(vfs, 0, block_tree)
# pvfs_instance.PVFS_write_block_data(vfs, 0, block_data)


# file_handle = pvfs_instance.create_PVFS_file_handle(vfs)


# pvfs_instance.PVFS_create(file_path)

# pvfs_instance.PVFS_create_size(file_path, vfs.blockSize)
# pvfs_instance.PVFS_open(file_path)
# vfs = pvfs_instance.PVFS_open_readonly(file_path)


# pvfs_instance.PVFS_close(vfs.fd)

# pvfs_instance.PVFS_allocate_block(vfs)

# channel_name = 'EEG1.dat'
# file_handle = pvfs_instance.PVFS_fcreate(vfs, channel_name)
# file_handle = pvfs_instance.PVFS_fopen(vfs, channel_name)