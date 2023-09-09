# MIT License

# Copyright (c) 2023 Voxed Team

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


# Copyright (c) 2013, Dan Jackson.
# All rights reserved.

# Redistribution and use in source and binary forms, with or without 
# modification, are permitted provided that the following conditions are met: 
# 1. Redistributions of source code must retain the above copyright notice, 
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, 
#    this list of conditions and the following disclaimer in the documentation 
#    and/or other materials provided with the distribution.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" 
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE 
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE 
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE 
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR 
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF 
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS 
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN 
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) 
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE 
# POSSIBILITY OF SUCH DAMAGE. 

import os
from PIL import Image
import cv2
import numpy as np
import os
import time
from datetime import datetime

XED_MAX_STREAMS = 10
SIZE_UINT_64 = 8
XED_STREAM_ALL = -1
RGB_MAX = 255
V_MAX = 4096

def read_int(file, num_bytes, byteorder="little"):
    return int.from_bytes(file.read(num_bytes), byteorder=byteorder)

class xed_reader:
    def __init__(self, filepath):
        # The path to the xed file
        self.filepath = filepath 
        
        # Xed file metadata
        self.xed_header = None
        self.stream_info = [None for _ in range(XED_MAX_STREAMS)]
        self.stream_index = [None for _ in range(XED_MAX_STREAMS)]
        self.total_events = 0
        self.global_index = None

        with open(filepath, mode='rb') as xed_file:
            # Reads XED Header
            self.xed_header = xed_header(xed_file)
                            
            # Checks if the header was found
            if(self.xed_header.filetype != b'EVENTS1\x00'):
                raise Exception(f"ERROR: File header not found! Expected EVENTS1, got {self.xed_header.filetype.decode('utf-8')}")

            if(self.xed_header.index_file_offset == 0):
                raise Exception("ERROR: Invalid data")
            
            # Go to the data section of the xed
            xed_file.seek(self.xed_header.index_file_offset)

            # Get num of end streams
            num_end_stream_info = read_int(xed_file, 2)
            if(num_end_stream_info != self.xed_header.num_streams):
                print("WARNING: Number of end stream information blocks not the same as the number of blocks")

            # Read info
            for i in range(num_end_stream_info):
                self.end_stream_info = xed_end_stream_info(xed_file, i)

                if self.end_stream_info.stream_number < XED_MAX_STREAMS and self.end_stream_info.stream_number < self.xed_header.num_streams:
                    if self.stream_index[self.end_stream_info.stream_number] != None:
                        raise Exception("ERROR: Stream already indexed")
                    
                    # @~168 <@120 in trimmed> (numIndexes *) File offset of xed_stream_index_t structures (e.g. = 0x4c098c2c / 0x4c0991e4 / 0x4c0925c / 0x4c0992d4 / 0x4c09934c)
                    offset = xed_file.tell()

                    for j in range(self.end_stream_info.numIndexes):
                        xed_file.seek(offset + j * SIZE_UINT_64)
                        index_offset = read_int(xed_file,8)
                        xed_file.seek(index_offset)
                        index = xed_stream_index(xed_file)
                        indexBase = j * self.end_stream_info.maxIndexEntries

                        # Read index entries
                        if indexBase + index.numEntries > self.end_stream_info.totalIndexEntries:
                            raise Exception("ERROR: Index for stream exceeds total index entries")
                        
                        self.stream_index[self.end_stream_info.stream_number] = [xed_index() for _ in range(self.end_stream_info.totalIndexEntries)]
                        for k in range(index.numEntries):
                            # Set stream id
                            self.stream_index[self.end_stream_info.stream_number][indexBase + k].streamId = self.end_stream_info.stream_number
                            # Read index entry
                            self.stream_index[self.end_stream_info.stream_number][indexBase + k].indexEntry = xed_index_entry_t(xed_file)
                            
                        
                        if self.end_stream_info.extraPerIndexEntry > 0:
                            # Read additional frame information
                            for k in range(index.numEntries):
                                self.stream_index[self.end_stream_info.stream_number][indexBase + k].frameInfo = xed_read_frame_info(xed_file, self.stream_index[self.end_stream_info.stream_number][indexBase + k].indexEntry, self.end_stream_info.extraPerIndexEntry)
                                break
                    
                    # Seek to after last index
                    xed_file.seek(offset + self.end_stream_info.numIndexes * SIZE_UINT_64)
                else:
                    xed_file.seek(SIZE_UINT_64 * self.end_stream_info.numIndexes, 1)   # @~168 <@120 in trimmed> (numIndexes *) File offset of xed_stream_index_t structures (e.g. = 0x4c098c2c / 0x4c0991e4 / 0x4c0925c / 0x4c0992d4 / 0x4c09934c)
                
                self.end_stream_info._unknown11 = read_int(xed_file,4); # @~192/176 ? timestamp/flags ? (e.g. = 0x8ad51914 / 0x965f0748 / 0xefc8076c / 0x3a400691 / 0x93a906b5)
                
                # Copy end stream info
                if self.end_stream_info.stream_number < XED_MAX_STREAMS and self.end_stream_info.stream_number < self.xed_header.num_streams:
                    self.stream_info[self.end_stream_info.stream_number] = self.end_stream_info
                else:
                    print(f"WARNING: Ignoring end stream information for stream number {self.end_stream_info.stream_number} as file maximum was {self.xed_header.num_streams} and compiled-in maximum was {XED_MAX_STREAMS}")
                
                #break
            
            # Seek back to first event
            xed_file.seek(24)

            # Create a super index of all events
            maxEvents = 0
            indexEntry = [0 for _ in range(XED_MAX_STREAMS)]
            numStreams = self.xed_header.num_streams

            if (numStreams > XED_MAX_STREAMS):
                numStreams = XED_MAX_STREAMS

            # Count the total number of index entries
            maxEvents = 0
            for i in range(numStreams):
                maxEvents += self.stream_info[i].totalIndexEntries
            
            # Allocate global index
            self.global_index = []

            # Create global index
            self.total_events = 0
            while(True):
                streamId = -1
                nextOffset = 0

                for j in range(numStreams):
                    #If we still have more events in the stream
                    if indexEntry[j] < self.stream_info[j].totalIndexEntries:
                        #TODO: check indexation
                        offs = self.stream_index[j][indexEntry[j]].indexEntry.frame_file_offset
                        if streamId < 0 or  offs < nextOffset:
                            streamId = j
                            nextOffset = offs

			    # Exit when no more entries
                if streamId < 0:
                    break

                # Check if we're trying to overflow the global index (shouldn't be possible)
                if (self.total_events >= maxEvents):
                    print(f"WARNING: Tried to overflow global index {maxEvents}")
                    break

                # Assign next global index entry to this stream's index entry
                self.global_index.append(self.stream_index[streamId][indexEntry[streamId]])
                self.total_events += 1      # Increment global index
                indexEntry[streamId] += 1   # Increment stream index

            if self.total_events != maxEvents:
                print(f"WARNING: Global index only has {self.total_events} / {maxEvents} entries")

        print("Xed reader created!")
                

class xed_header:
    def __init__(self, xed_file):
        self.filetype = xed_file.read(8) #EVENTS1\x00
        self.version = read_int(xed_file, 4)            # fget_uint32(xed_file)
        self.num_streams = read_int(xed_file, 4)        # fget_uint32(xed_file)
        self.index_file_offset = read_int(xed_file, 4)  # fget_uint32(xed_file)


class xed_index_entry_t:
    def __init__(self, xed_file):
        self.frame_file_offset = read_int(xed_file,8) # @ 0 (e.g. 0x000000004c002bfc, can point to first frame)
        self.frame_timestamp = read_int(xed_file,8)   # @ 8 (e.g. 0x000000038f84d534, or 0 if none)
        self.data_size = read_int(xed_file,4)          # @16 (e.g. 614400)
        self.data_size2 = read_int(xed_file,4)        # @20 (e.g. 614400)


class xed_frame_info:
    def __init__(self, xed_file): #XedReadFrameInfo
        #There is a strange value been passed to unknown1, but it do not affect the code execution
        self._unknown1 = read_int(xed_file, 2, byteorder="big")       # @ 0 <big-endian> ? = 1
        self._unknown2 = read_int(xed_file, 2, byteorder="big")       # @ 2 <big-endian> ? = 0
        self._unknown3 = read_int(xed_file, 2, byteorder="big")       # @ 4 <big-endian> ? = 1
        self._unknown4 = read_int(xed_file, 2, byteorder="big")       # @ 6 <big-endian> ? = 1
        self.width = read_int(xed_file, 2, byteorder="big")           # @ 8 <big-endian> Width (= 640)
        self.height = read_int(xed_file, 2, byteorder="big")          # @10 <big-endian> Height (= 480)
        self.sequence_number = read_int(xed_file, 2, byteorder="big") # @12 <big-endian> Frame sequence number (e.g. = 0x00000f86 / 0x00000f87 / 0x00000f88 / ... / 0x000017a1 = 6049)
        self._unknown5 = read_int(xed_file, 6, byteorder="big")       # @14 <big-endian> ? = 0
        self.timestamp = read_int(xed_file, 4, byteorder="big")       # @20 <big-endian> Timestamp (e.g. = 0x0e26da91 / 0x0e275775 / 0x0e275c5d / ... / 0x1246ac60)
                                                                      # @24 <end>
        print(self._unknown1,
                self._unknown2,
                self._unknown3,
                self._unknown4,
                self.width,
                self.height,
                self.sequence_number,
                self._unknown5,
                self.timestamp)


def xed_read_frame_info(xed_file,  index_entry:xed_frame_info, frame_info_size):
    # Clear current value
    frame_info_len = 0

    if index_entry != None:
        frame_info_len = 24

        # Work ou how much to read
        if frame_info_size < frame_info_len:
            frame_info_len = frame_info_size

        # Reads the frame info
        if frame_info_len > 0:
            index_entry = xed_frame_info()
    else:
        #print("None frame passed")
        pass

    # Skip unread data
    if (frame_info_size > frame_info_len):
        xed_file.seek(frame_info_size - frame_info_len, 1)

    return index_entry

class xed_end_stream_info:
    def __init__(self, xed_file, iteration_num):
        self._unknown1 = read_int(xed_file, 2)         # @  0 = 0xffff
        self._unknown2 = read_int(xed_file, 2)         # @  2 = 0xffff

        if self._unknown1 != int("0xffff",16) or self._unknown2 != int("0xffff",16):
            raise Exception("ERROR: End stream info does not start with expected 0xffff 0xffff")
        
        # Number of the stream
        self.stream_number = read_int(xed_file,2)      # @  4 = 0/1/2/3/4
        if(self.stream_number != iteration_num):
            print("WARNING: End stream info is not for the expected stream")

        self.extraPerIndexEntry = read_int(xed_file,2); # @  6 Length of xed_frame_info_t in index = 24 [have seen trimmed file with length 0, with no xed_frame_info_t entries in the index]
        self.totalIndexEntries = read_int(xed_file,4)   # @  8 Total number of frames (index entries) in the file = 2078 / 2
        self.frameSize = read_int(xed_file,4)           # @ 12 Size of frame (e.g. = 614400 / 0 / 0 / 0 / 0)
        self.maxIndexEntries = read_int(xed_file,4)     # @ 16 max entries per index = 1024
        self.numIndexes = read_int(xed_file,4)          # @ 20 number of indexes = 3 / 1 / 1 / 1 / 1

        self.event_0 = xed_index_entry_t(xed_file)      # @ 24 Index entry for event 0 (xed_initial_data_t) information
        self.event_1 = xed_index_entry_t(xed_file)      # @ 48 Index entry for event 1 (xed_event_empty_t) information

        self._unknownEvent0 = [read_int(xed_file, 1) for _ in range(24)] # @72
        self._unknownEvent1 = [read_int(xed_file, 1) for _ in range(24)] # @96

        xed_read_frame_info(xed_file,None,self.extraPerIndexEntry)
        xed_read_frame_info(xed_file,None,self.extraPerIndexEntry)


# Index [e.g. first @627967580 = 0x256e065c | second @1257211508 = 0x4aef8674 | ... | last @1275694124 = 0x4c098c2c] (24 bytes), remaining index entries for each stream written at the end of the file, followed by an index location
class xed_stream_index:
    def __init__(self, xed_file):
        self.packetType = read_int(xed_file,2)      # @0 = 0xffff
        if self.packetType != int("0xffff",16):
            raise Exception("ERROR: Index for stream does not start with expected 0xffff")
        
        self._unknown1  = read_int(xed_file,2)      # @2 = 0
        self.numEntries = read_int(xed_file,4)      # @4 (e.g. = 1024 | 1024 | ... | 30 / 2 / 2 / 2 / 2)
        self._unknown2  = read_int(xed_file,4)      # @8 (e.g. = 0xf934b72c | 0xe418b73d | ... | 0x1ea8f030 / 0x6f970162 / 0xa75d020c / 0x37c900b8 / 0x6f8f0162)
        self._unknown3  = read_int(xed_file,4)      # @12 = 0
        self._unknown4  = read_int(xed_file,4)      # @16 = 0
        self._unknown5  = read_int(xed_file,4)      # @20 = 0
                                    # @24 <end>, followed by


# Reader type for indexing the file
class xed_index:
    def __init__(self):
        self.streamId = None   #uint16_t
        self.indexEntry = None #xed_index_entry_t
        self.frameInfo = None  #xed_frame_info_t


def xed_get_num_events(reader: xed_reader, stream: int):
    if stream == XED_STREAM_ALL:
        return reader.total_events
    elif stream >= 0 and stream < reader.xed_header.num_streams and stream < XED_MAX_STREAMS:
        return reader.stream_info[stream].totalIndexEntries
    else:
        raise Exception("Invalid argument")
    

class xed_event:
    def __init__(self, xed_file):
        self.streamId  = read_int(xed_file, 2) # uint16_t @ 0 Stream ID
        self._flags    = read_int(xed_file, 2) # uint16_t @ 2 ? Flags
        self.length    = read_int(xed_file, 4) # uint32_t @ 4 Length of payload in this event type (may also have a xed_frame_info_t before the payload)
        self.timestamp = read_int(xed_file, 8) # uint64_t @ 8 Timestamp
        self._unknown1 = read_int(xed_file, 4) # uint32_t @16 ? Unknown value
        self.length2   = read_int(xed_file, 4) # uint32_t @20 Usually, but not always, set the same as length.


# Frame information (24 bytes)
class xed_frame_info:
    def __init__(self):
        self._unknown1      = 0    # uint16_t @ 0 <big-endian> ? = 1
        self._unknown2      = 0    # uint16_t @ 2 <big-endian> ? = 0
        self._unknown3      = 0    # uint16_t @ 4 <big-endian> ? = 1
        self._unknown4      = 0    # uint16_t @ 6 <big-endian> ? = 1
        self.width          = 0    # uint16_t @ 8 <big-endian> Width (= 640)
        self.height         = 0    # uint16_t @10 <big-endian> Height (= 480)
        self.sequenceNumber = 0    # uint32_t @12 <big-endian> Frame sequence number (e.g. = 0x00000f86 / 0x00000f87 / 0x00000f88 / ... / 0x000017a1 = 6049)
        self._unknown5      = 0    # uint32_t @14 <big-endian> ? = 0
        self.timestamp      = 0    # uint32_t @20 <big-endian> Timestamp (e.g. = 0x0e26da91 / 0x0e275775 / 0x0e275c5d / ... / 0x1246ac60)
                                   #          @24 <end>


# Get an event index
def xed_get_index_entry(reader, stream, index):
    if (reader == None):
            return None # XED_E_POINTER

    if stream == XED_STREAM_ALL:
        if index >= 0 and index < reader.total_events:
            return reader.global_index[index]
        else:
            return None; # XED_E_INVALID_ARG
    elif stream >= 0 and stream < reader.xed_header.num_streams and stream < XED_MAX_STREAMS:
        if index >= 0 and index < reader.stream_info[stream].totalIndexEntries:
            return reader.stream_index[stream][index]
        else:
            return None # XED_E_INVALID_ARG
    else:
        return None;    # XED_E_INVALID_ARG;


def xed_read_event(xed_file, reader, stream, index, buffer, bufferSize,verbose):
    indexEntry = xed_get_index_entry(reader, stream, index)

    xed_file.seek(indexEntry.indexEntry.frame_file_offset)

    if(verbose):
        print(f"<@{xed_file.tell()}>")

    event = xed_event(xed_file)
    frameInfo = xed_frame_info()

    # Assume the payload size is the length specified
    size = event.length

    # If this is an index, modify for the size of the index
    if event.streamId == int("0xffff",16):
        additional = 24
        print(f"NOTE: Unexpected index {event.streamId}.{event._flags} -- skipping assuming has 24-bytes additional data {event.length}/{event.length2} entries")
        size *= (24 + additional)
    elif event.streamId == reader.xed_header.num_streams:
        # Probably the index location packet, stop parsing
        raise Exception(f"ERROR: Unexpected stream number (probably the index location packet) {event.streamId}")
    elif event.streamId > reader.xed_header.num_streams:
        # Unexpected stream number
        raise Exception("ERROR: Unexpected stream number")
    elif event.timestamp != 0:
        # If we have a timestamp, read the event info first
        frameInfo._unknown1 = read_int(xed_file, 2, byteorder="big")      
        frameInfo._unknown2 = read_int(xed_file, 2, byteorder="big")      
        frameInfo._unknown3 = read_int(xed_file, 2, byteorder="big")      
        frameInfo._unknown4 = read_int(xed_file, 2, byteorder="big")      
        frameInfo.width = read_int(xed_file, 2, byteorder="big")          
        frameInfo.height = read_int(xed_file, 2, byteorder="big")         
        frameInfo.sequence_number = read_int(xed_file, 2, byteorder="big")
        frameInfo._unknown5 = read_int(xed_file, 6, byteorder="big")      
        frameInfo.timestamp = read_int(xed_file, 4, byteorder="big")      

    if(verbose):
        print(f"<{event.length}|{event.length2}={size}>") #, event->length, event->length2, size);
        print(f"={event.streamId}.{event._flags};")    #, event->streamId, event->_flags);

    # Read buffer
    readSize = size
    if size > bufferSize:
        size = bufferSize

    buffer = xed_file.read(readSize)

    if size < bufferSize:
        xed_file.seek(size - readSize, 1)

    return event, frameInfo, buffer
            
def xed_decode(filepath, store_path="", verbose=True):
    start_time = time.perf_counter()
    start_date_time = datetime.now()

    if(not os.path.isfile(filepath)):
        raise Exception("File not found!")

    bufferSize = 1024 * 768 * 3
    reader = xed_reader(filepath)
    buffer = bytearray(bufferSize)
    count_0, count_1 = 0, 0

    with open(reader.filepath, mode='rb') as xed_file:

        if verbose:
            print("XED,packet,stream,type,len,time,unknown,len2"
                ",unk1,unk2,unk3,unk4,width,height,seq,unk5,time")
            # Adjust read position
            print("f: ",xed_file.tell())

        # Read packets
        for packet in range(xed_get_num_events(reader, XED_STREAM_ALL)):
            frame, frameInfo, buffer = xed_read_event(xed_file, reader, XED_STREAM_ALL, packet, buffer, bufferSize,verbose)
            buffer = bytearray(buffer)

            if verbose == True:
                print(f"XED,{packet}    ,{frame.streamId}    ,{frame._flags}  ,{frame.length} ,{frame.timestamp},{hex(frame._unknown1)} ,{frame.length2}  ")
                
                if frame.streamId != int("0xffff",16):
                    #     ",unk1,unk2,unk3,unk4,width,height,seq,unk5,time"
                    print(f",{frameInfo._unknown1}  ,{frameInfo._unknown2}  ,{frameInfo._unknown3}  ,{frameInfo._unknown4}  ,{frameInfo.width}   ,{frameInfo.height}    ,{frameInfo.sequenceNumber} ,{frameInfo._unknown5}  ,{frameInfo.timestamp}  ")
                else:
                    print(",,,,,,,,,", end="")
    
            if frame.length == frameInfo.width * frameInfo.height * 2:
                # Not tested

                # Save snapshots
                if (count_0 % 30) == 0 and frameInfo.width > 0 and frameInfo.height > 0:
                    width = frameInfo.width
                    height = frameInfo.height

                    i = 0
                    for y in range(height):
                        p = int.from_bytes(buffer[:2], byteorder="big") +y * (width * 2)
                        for x in range(width):
                            #v = int.from_bytes(buffer[:2], byteorder="big")
                            v = p
                            v &= int("0x0fff",16)  # Mask for depth-only

                        # Stretch
                        if v < 850:
                             v = 0
                        else: 
                            v = (int)((v - 850) * 4096 / (4000 - 850))
                            if v >= 4096:
                                v = 4095
                        
                        z = (int)(RGB_MAX * (v % (V_MAX / 6 + 1)) / (V_MAX / 6 + 1))

                        if (v < (1 * V_MAX / 6)):
                            r = RGB_MAX
                            g = z
                            b = 0 
                        elif (v < (2 * V_MAX / 6)):
                            r = RGB_MAX - z
                            g = RGB_MAX
                            b = 0
                        elif (v < (3 * V_MAX / 6)):
                            r = 0
                            g = RGB_MAX
                            b = z
                        elif (v < (4 * V_MAX / 6)):
                            r = 0
                            g = RGB_MAX - z
                            b = RGB_MAX
                        elif (v < (5 * V_MAX / 6)):
                            r = z
                            g = 0
                            b = RGB_MAX
                        else:
                            r = RGB_MAX
                            g = z
                            b = RGB_MAX

                        # Convert to RGB555
                        v = ((r >> 3) << 10) | ((g >> 3) << 5) | ((b >> 3) << 0)

                        v += 2
                        v = int.to_bytes(v,2,byteorder="little")

                        # Write back (little endian)
                        # buffer[y * (width * 2) + i] = v
                        # buffer[y * (width * 2) + i + 1] = v >> 8
                        buffer[y * (width * 2) + i : y * (width * 2) + i + 1] = v

                    img = Image.frombytes("P", (width,height), buffer)
                    img_array = np.array(img)                          
                    #img_rgb = cv2.cvtColor(img_array, cv2.COLOR_BayerGRBG2BGR) # Conversion to RGB
                    cv2.imwrite(f"out16_{count_0/30}.bmp", img_array)
                    return img_array

                count_0 += 1

            elif frame.length == frameInfo.width * frameInfo.height * 1: # Colour data in GRBG bayer pattern
                    # Save snapshots
                    if (count_1 % 10) == 0 and frameInfo.width > 0 and frameInfo.height > 0:
                        width = frameInfo.width
                        height = frameInfo.height

                        # Generate img
                        filename = f"out32-{count_1/10}.bmp"
                        filename = os.path.join(store_path,filename)
                        extract_image_from_bytes(buffer, width, height, filename)

                    count_1 += 1

    if(store_path != ""):
        print(f"\nIMAGES STORED AT {store_path}")
    
    finish_time = time.perf_counter()
    finish_datetime = datetime.now()

    print("\nXED DECODED! \n" + 
           f"START TIME: {start_date_time}\n"+
           f"FINISH TIME: {finish_datetime}\n"+
           f"ELAPSED TIME: {finish_time - start_time}")


def extract_image_from_bytes(buffer, width, height, filename):
    img = Image.frombytes("L", (width,height), buffer)         # Open image as grayscale from bytes
    img_array = np.array(img)                          
    img_rgb = cv2.cvtColor(img_array, cv2.COLOR_BayerGRBG2BGR) # Conversion to RGB
    cv2.imwrite(filename, img_rgb)
    return img_rgb


def main():
    filepath = input("Filepath:")

    print("NOTE: Processing:", filepath)
    xed_decode(filepath, verbose=True)
    print("\nNOTE: End processing\n")

if __name__ == "__main__":
    main()