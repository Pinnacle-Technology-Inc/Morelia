
import numpy
import matplotlib.pyplot as plt
import math
def plot_freqs(time_series):

    n = len(time_series)
    fft = numpy.fft.fft(time_series)
    freqs = numpy.fft.fftfreq(n, d=1/2000)

    plt.figure()

    plt.style.use('seaborn-poster')
    plt.figure(figsize=(10,6))
    plt.plot(freqs[:n//2], numpy.abs(fft[:n//2]) * 2 / n)
    plt.xlabel('Hz')
    plt.ylabel('uV')
    plt.grid(True)
    plt.show()

sample_rate = 2000
delta = 1.0 / sample_rate
t = numpy.arange(0,1,delta)

freq = 1
x = 3 * numpy.sin(2*numpy.pi*freq*t)
freq = 4
x += numpy.sin(2*numpy.pi*freq*t)
freq = 7
x += 0.5 * numpy.sin(2*numpy.pi*freq*t)

plt.figure(figsize = (8,6))
plt.plot(t,x,'r')
plt.show()