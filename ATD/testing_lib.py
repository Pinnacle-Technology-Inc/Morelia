from Morelia.Devices import Pod8206HR
from Morelia.Devices import PodATD
from Morelia.packet.data import DataPacket
from Morelia.Stream.sink import EDFSink, BufferSink
from Morelia.Stream.data_flow import DataFlow
import multiprocessing as mp
import matplotlib.pyplot as plot
from scipy.optimize import curve_fit
from pod_lib import *
import numbers, math, time, os, numpy

MAX_DAC_VALUE = 65535
SINE = 0
DC = 1
WHITE_NOISE = 2
SQUARE = 3
CHA = 0
CHB = 1
CHC = 2
CHD = 3
TYPE_ATD = 99
TYPE_8206HR = 48

#convert a uV value to a DAC value
def uV(uV_value:int, gain: int):
    #max scale is 65535, which is 409.6 uV at 100x gain or 4096uV at 10x gain
    if gain == 10:
        if uV_value > 4096 or uV_value < 0:
            raise Exception("uV value out of range")
        else:
            return int( (uV_value / 4096.0) * MAX_DAC_VALUE)
    elif gain == 100:
        if uV_value > 409 or uV_value < 0:
            raise Exception("uV value out of range")
        else:
            return int( (uV_value / 409.6) * MAX_DAC_VALUE)
    else:  
        raise Exception("Unknown gain value")
    
    

def plot_fft(time_series, frequency):
    
    time = numpy.arange(0,1,(1/frequency) )
    time = time[:frequency]

    channel_values = [[] for _ in range(3)]

 
    for x in time_series:
        channel_values[0].append(x[0])
        channel_values[1].append(x[1])
        channel_values[2].append(x[2])

    plot.figure(figsize = (20,6))
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

def sine_function(x, amplitude, frequency, phase, offset):
    return (amplitude * numpy.sin((2 * numpy.pi * frequency * x) + phase) + offset)

def zero_crossing(data, frequency):
    index = 0
    # set the search range to be equal to 2 periods
    search_range = int(len(data) / (frequency / 2))
    values = [] 
    decreasing = False
    for x in data[:search_range]:
        values.append(abs(x))   #rectify the data and shove it into values
    minimum = values[0] # Just set the minimum to the first value
    for x in range(len(values)):
        if values[x] < minimum:
            index = x
            minimum = values[x]
    # if this is a downward zero crossing, make the index negative
    if data[index + 10] < 0:
        decreasing = True
    
    return index, decreasing

def sine_fit(buffer, amplitude, frequency):
    # find how many channels we have
    num_channels = 0
    # TTL values are non-numeric, boolean HIGH/LOW values, so only count the numerical channels
    for x in buffer[0][1]:
        if isinstance(x, numbers.Number):
            num_channels = num_channels + 1
 
    # Create the lists to handle data
    data = []
    fit_params = []
    fit_error = []
    
    # create each channel data list
    for x in range(num_channels):
        data.append([])
        fit_params.append([])
        fit_error.append([])
        
    # populate the data
    for x in range(num_channels):
        for y in buffer:
            data[x].append(y[1][x])

    # find the zero crossing index
    # The same sine wave is being fed to all channels, so use Ch0 as the baseline
    # note that different filters will induce phase delay, so if channels are configured differently this will show up
    zero_index, decreasing = zero_crossing(data[0], frequency)
    print(f"Zero Index = {zero_index}, Decreasing = {decreasing}")
    
    # Giving curve_fit less data to fit with seems to work better
    length = int(len(data[0])/4) 
    
     #Cut off the data before the zero crossing, and reduce to new length
    for x in range(num_channels):
        data[x] = data[x][zero_index:]
        data[x] = data[x][:length]
        #if the zero crossing was pos > neg, invert the data so it's always increasing
        if decreasing:
            for y in range(length):
                data[x][y] = -data[x][y]
      
    # Create the time series, and compensate for the data we've thrown away        
    time = numpy.linspace(0, length / len(buffer), length)
    
    # create the initial guess, based off our input parameters
    init = [amplitude,frequency,0,0]
    
    # create the initial plot settings
    #plot.style.use('dark_background')
    #plot.ylabel('Amplitude (uV)')
    #plot.xlabel('Time (s)')
    #plot_title = f"{amplitude} uV @ {frequency} Hz"
    #plot.title(plot_title)
    
    # Sine fit
    for x in range(num_channels):
        fit_params[x], covariance = curve_fit(sine_function, time, data[x], p0=init)
        fit_error[x] = numpy.sqrt(numpy.diag(covariance))
        #return value order is amp, freq, phase, offset for both params and error
        #amp, freq, phase, offset = fit_params[x] or fit_error[x]
      
      #  amp_fit, freq_fit, phase_fit, offset_fit = fit_params[x]
        
      #  sine_fit = sine_function(time, amp_fit, freq_fit, phase_fit, offset_fit)
      #  plot.plot(time, data[x], '+', label='x', color='red')
      #  plot.plot(time, sine_fit, 'x', label='f', color='green')
        
    #plot.legend()
    #plot.show()
    
    return time, data, fit_params, fit_error


# def sine_fit(buffer, amplitude, frequency, sample_rate=2000):
    
#     # Find number of numeric channels (ignore TTL channels)
#     num_channels = 0
#     for x in buffer[0][1]:
#         if isinstance(x, numbers.Number):
#             num_channels += 1

#     data = [[] for _ in range(num_channels)]
#     fit_params = [[] for _ in range(num_channels)]
#     fit_error = [[] for _ in range(num_channels)]

#     # Extract channel data
#     for channel in range(num_channels):
#         for sample in buffer:
#             data[channel].append(sample[1][channel])

#     # Find zero crossing using channel 0
#     zero_index, decreasing = zero_crossing(data[0], frequency)

#     print(f"Zero Index = {zero_index}, Decreasing = {decreasing}")

#     # Use all remaining samples instead of only 1/4
#     for channel in range(num_channels):
#         data[channel] = data[channel][zero_index:]

#         # Make all fits start with a rising edge
#         if decreasing:
#             data[channel] = [-x for x in data[channel]]

#     length = len(data[0])

#     # FIX: correct time axis
#     time = numpy.arange(length) / sample_rate

#     init = [
#         amplitude,
#         frequency,
#         0,
#         numpy.mean(data[0])
#     ]

#     for channel in range(num_channels):

#         print(
#             f"Channel {channel}: "
#             f"mean={numpy.mean(data[channel]):.3f}, "
#             f"std={numpy.std(data[channel]):.3f}, "
#             f"range={numpy.ptp(data[channel]):.3f}"
#         )
        
#         fit_params[channel], covariance = curve_fit(
#             sine_function,
#             time,
#             data[channel],
#             p0=init,
#             bounds=(
#                 [
#                     0,
#                     frequency * 0.5,
#                     -numpy.pi,
#                     -100
#                 ],
#                 [
#                     amplitude * 2,
#                     frequency * 1.5,
#                     numpy.pi,
#                     100
#                 ]
#             )
#         )

#         fit_error[channel] = numpy.sqrt(
#             numpy.diag(covariance)
#         )

#     return time, data, fit_params, fit_error
    
    
def validate_test(fit_params, fit_error, target_vals, frequency):
    
    num_channels = len(fit_params)
    error = 0
    
    amp_tolerance = 5   
    noise_tolerance = 1
    freq_tolerance = frequency * 0.1 # 10% frequency tolerance; not sure this matters
    dc_tolerance = 5
    
    for x in range(num_channels):
       amp, freq, phase, offset = fit_params[x]
       amp_err, freq_err, phase_err, offset_err = fit_error[x]
       print(f'Running test on CH{x}:')
       # test amplitude
       amp = abs(amp) # for some reason the sine fit function regularly returns things 180deg out of phase, so just absolute value it. 
       if math.isclose(amp, target_vals[x], abs_tol=amp_tolerance):
            print(f"Amplitude check PASS - Actual = {amp}, Expected = {target_vals[x]}")
       else:
            print(f"Amplitude check FAIL - Actual = {amp}, Expected = {target_vals[x]}")
            error += 1         
       # test noise
       if amp_err < noise_tolerance:
            print(f"Noise check PASS - Actual = {amp_err}, Max = {noise_tolerance}")
       else:
            print(f"Noise check FAIL - Actual = {amp_err}, Max = {noise_tolerance}")
            error += 2 
       # test frequency
       if math.isclose(freq, frequency, abs_tol = freq_tolerance):
            print(f"Frequency check PASS - Actual = {freq}, Expected = {frequency}")
       else:
            print(f"Frequency check FAIL - Actual = {freq}, Expected = {frequency}")
            error += 4
       # test DC offset
       if offset < dc_tolerance:
            print(f"Offset check PASS - Actual = {offset}, Max = {dc_tolerance}")
       else:
            print(f"Noise check FAIL - Actual = {offset}, Max = {dc_tolerance}")
            error += 8
    
       error *= 2 
    
    return error
   
def execute_test(test_name:str, test_length:int, device):
    from multiprocessing import Manager
    manager = Manager()
    buffer = manager.list()

    edf_path = test_name + ".edf"

    edf_sink = EDFSink(edf_path, device)
    buffer_sink = BufferSink(buffer, device)

    mapping = [ (device, [buffer_sink, edf_sink]) ]

    flowgraph = DataFlow(mapping)

    print ("Waiting for any hardware changes to settle")
    time.sleep(1)

    print ("Starting test " + test_name + ": duration " + str(test_length) + "s")# Connect to an 8206HR device

    flowgraph.collect_for_seconds(test_length)

    #remove the channel tags
    buffer = buffer[2:]

    frequency = int(len(buffer) / test_length)

    print ("Number of samples collected: " + str(len(buffer)))
    print ("Actual sample frequency: " + str(frequency))
    
    return buffer



