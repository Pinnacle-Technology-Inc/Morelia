
from Morelia.Devices import Pod8206HR
from Morelia.Devices import PodATD
from Morelia.packet.data import DataPacket
from Morelia.Stream.sink import EDFSink, BufferSink
import Morelia.Stream.data_flow as data_flow
import multiprocessing as mp
import time
import numpy
import matplotlib.pyplot as plot


MAX_DAC_VALUE = 65535

# Connect to an 8206HR device
pod = Pod8206HR('/dev/ttyUSB0', 10)
# have to do this until sample rate property is fixed
if isinstance(pod.sample_rate, tuple):
    pod.sample_rate = pod.sample_rate[0]
    
# Connect to an ADT device
atd = PodATD('/dev/ttyUSB1')

def plot_fft(time_series, frequency):
    
    time = numpy.arange(0,1,(1/frequency) )
    time = time[:frequency]

    channel_values = [[] for _ in range(3)]

 
    for x in time_series:
        channel_values[0].append(x[0])
        channel_values[1].append(x[1])
        channel_values[2].append(x[2])

    plot.figure(figsize = (10,6))
    plot.subplot(321)
    plot.plot(time, channel_values[0], 'r')
    plot.subplot(323)
    plot.plot(time, channel_values[1], 'r')
    plot.subplot(325)
    plot.plot(time, channel_values[2], 'r')
 
    fft = numpy.fft.rfft(channel_values[0])
    fft = numpy.abs(fft)
    freqs = numpy.fft.fftfreq(len(fft), 1/1000)
    freqs = numpy.abs(freqs)    
    plot.subplot(322)
    plot.plot(freqs[:50], fft[:50])
    
    fft = numpy.fft.rfft(channel_values[1])
    fft = numpy.abs(fft)
    freqs = numpy.fft.fftfreq(len(fft), 1/1000)
    freqs = numpy.abs(freqs)    
    plot.subplot(324)
    plot.plot(freqs[:50], fft[:50])
    
    fft = numpy.fft.rfft(channel_values[2])
    fft = numpy.abs(fft)
    freqs = numpy.fft.fftfreq(len(fft), 1/1000)
    freqs = numpy.abs(freqs)    
    plot.subplot(326)
    plot.plot(freqs[:50], fft[:50])
    
    
    plot.show()


def execute_frequency_test(test_name:str, test_length:int):
    # Set up the list object for the buffer
    manager = mp.Manager()
    buffer = manager.list()
    # create the sink objects for EDF and buffer
    buffer_dump = BufferSink(buffer, pod)
    edf_dump = EDFSink(test_name + '.edf', pod)
    #create the input/output mappings and connect the flowgraph
    mapping = [(pod, [buffer_dump, edf_dump])]
    flowgraph = data_flow.DataFlow(mapping)

    print ("Waiting for any hardware changes to settle")
    time.sleep(1)

    print ("Starting test " + test_name + ": duration " + str(test_length) + "s")

    flowgraph.collect_for_seconds(test_length)

    #remove the channel tags
    buffer = buffer[2:]

    frequency = int(len(buffer) / test_length)

    print ("Number of samples collected: " + str(frequency))

    sample_dc_value = 0
    sample_length = len(buffer) 
    time_series = []

    for x in buffer:
        sample_dc_value += abs(x[1][0]) #rectify the input data
        time_series.append((x[1][0], x[1][1], x[1][2]))

    plot_fft(time_series, frequency)

    sample_dc_value /= sample_length
    print ("Average DC value: " + str(sample_dc_value))


#Set up the ATD for the conditions of the test
atd.write_read('SET CHANNEL CONFIG', (0, 0, 50000)) # Setup channel to DAC A
atd.write_read('SET CHANNEL CONFIG', (1, 0, 1000))   # Sets channel to DAC A
atd.write_read('SET CHANNEL CONFIG', (2, 0, 1000)) # Sets channel to DAC A
atd.write_read('SET CHANNEL CONFIG', (3, 1, 0)) # Sets channel to DAC A
atd.write_read('SET FREQ', 20)
#Set up the pod device for the test
pod.write_read('SET LOWPASS', (0,30) )
pod.write_read('SET LOWPASS', (1,30) )
pod.write_read('SET LOWPASS', (2,30) )

# run the first test
execute_frequency_test('20hz Test - 30Hz LP', 1)

# Set up the next test
atd.write_packet('SET FREQ', 40)
execute_frequency_test('40hz Test - 30Hz LP', 1)

# set up the next test
pod.write_packet('SET LOWPASS', (0,50) )
pod.write_packet('SET LOWPASS', (1,50) )
pod.write_packet('SET LOWPASS', (2,50) )
execute_frequency_test('40hz Test - 50Hz LP', 1)

atd.write_read('SET DIGITAL IO', (0,0))
atd.write_read('SET DIGITAL IO', (1,0))
atd.write_read('SET DIGITAL IO', (2,0))
atd.write_read('SET DIGITAL IO', (3,0))

time.sleep(1)

ttl_vals  = pod.write_read('GET TTL IN', 0).payload
ttl_vals += pod.write_read('GET TTL IN', 1).payload
ttl_vals += pod.write_read('GET TTL IN', 2).payload
ttl_vals += pod.write_read('GET TTL IN', 3).payload

print("Setting ATD TTL outs to 0: " + str(ttl_vals))

atd.write_read('SET DIGITAL IO', (0,1))
atd.write_read('SET DIGITAL IO', (1,1))
atd.write_read('SET DIGITAL IO', (2,1))
atd.write_read('SET DIGITAL IO', (3,1))

time.sleep(1)

ttl_vals  = pod.write_read('GET TTL IN', 0).payload
ttl_vals += pod.write_read('GET TTL IN', 1).payload
ttl_vals += pod.write_read('GET TTL IN', 2).payload
ttl_vals += pod.write_read('GET TTL IN', 3).payload

print("Setting ATD TTL outs to 1: " + str(ttl_vals))

# have to do this first so we don't have outputs talking at each other
atd.write_read('GET DIGITAL IO', 0)
atd.write_read('GET DIGITAL IO', 1)
atd.write_read('GET DIGITAL IO', 2)
atd.write_read('GET DIGITAL IO', 3)

pod.write_read('SET TTL OUT', (0,0))
pod.write_read('SET TTL OUT', (1,0))
pod.write_read('SET TTL OUT', (2,0))
pod.write_read('SET TTL OUT', (3,0))

time.sleep(1)

ttl_vals = atd.write_read('GET DIGITAL IO', 0).payload
ttl_vals += atd.write_read('GET DIGITAL IO', 1).payload
ttl_vals += atd.write_read('GET DIGITAL IO', 2).payload
ttl_vals += atd.write_read('GET DIGITAL IO', 3).payload

print("Setting 8206 TTL outs to 0: " + str(ttl_vals))

pod.write_read('SET TTL OUT', (0,1))
pod.write_read('SET TTL OUT', (1,1))
pod.write_read('SET TTL OUT', (2,1))
pod.write_read('SET TTL OUT', (3,1))

time.sleep(1)

ttl_vals = atd.write_read('GET DIGITAL IO',  0).payload
ttl_vals += atd.write_read('GET DIGITAL IO', 1).payload
ttl_vals += atd.write_read('GET DIGITAL IO', 2).payload
ttl_vals += atd.write_read('GET DIGITAL IO', 3).payload

print("Setting 8206 TTL outs to 1: " + str(ttl_vals))
