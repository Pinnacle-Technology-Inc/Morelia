import shutil

from testing_lib import *
from pathlib import Path

gain = 100
input_uV = 200
#target vales for each channel on each test
#3 sets, one for each HPF config
hpf_types = ['SL', 'SE', 'SE3']
#Target test values - each array contains the test values for one HPF config (SE, SL, SE3)
#Then the individual test values are contained in the sub arrays, containing one value for each channel
target_vals = [ [[200, 200, 130], [0,0,0], [200,200,177]], [[200, 200, 130], [0,0,0], [200,200,177]], [[200, 200, 200], [0,0,0], [200,200,200]] ]
# increment this after each test
test_number = 0
test_length = 2

if __name__ == "__main__":

    root = Path(__file__).resolve().parent

    output_dir = '_preamp_results'
    output_path = f'{root}'
    log_file = 'preamp_test_log.txt'

    test1_name = '-20hz-30lpf-preamp'
    test2_name = '-40hz-30lpf-preamp'
    test3_name = '-40hz-50lpf-preamp'

    montage_file = f"{root}/8206mtg.mtg"
    outfiles = []
    outdirs = []

    pod_list = pod_scan(usb_scan())
    atd = []
    dut_list = []

    test_freq = 20
    test_freq_delta = 10

    # add all the devices
    if pod_list != []:
        for x in pod_list:
            print ('Found: ' + x['PORT'] + ' type: ' + str(x['TYPE']) + ' ID: ' + str(x['ID']))
            if x['TYPE'] == TYPE_ATD:
                atd = PodATD(x['PORT'])
                print ('ATD Added - ' + x['PORT'])
            if x['TYPE'] == TYPE_8206HR:
                dut_list.append((x['ID'], Pod8206HR(x['PORT'],gain)))
                print ('8206HR Added - ' + x['PORT'])
                if x['ID'] == 65535:
                    print ('Device ID not set - Results will overwrite - firmware update recommended')
        if atd == []:
            raise Exception ('ATD Not Found - aborting')
        elif dut_list == []:
            raise Exception ('No 8206HRs Found - aborting')
        
    # have to do this until sample rate property is fixed
    for x in dut_list:
        x[1].sample_rate = 2000

    #Set up the ATD for the conditions of the test - sine wave, half of full scale
    atd.write_read('SET CHANNEL CONFIG', (CHA, SINE, uV(input_uV, gain))) 
    atd.write_read('SET CHANNEL CONFIG', (CHB, SINE, uV(input_uV, gain))) 
    atd.write_read('SET CHANNEL CONFIG', (CHC, SINE, uV(input_uV, gain))) 
    atd.write_read('SET CHANNEL CONFIG', (CHD, SINE, uV(input_uV, gain))) 

    #Set up the pod devices for theoutput_dir test
    atd.write_read('SET FREQ', (test_freq,))

    # run the first test on each device
    for x in dut_list:
        errors = []
        dev_id = str(x[0])
        folder_name = f"{dev_id}{output_dir}"
        file_path = str(root / folder_name)
        os.makedirs(file_path, exist_ok=True)
        outdirs.append(file_path)
        hpf = x[1].write_read('GET FILTER CONFIG').payload[0]
        try:
            print(f'HPF Type = {hpf_types[hpf]}')
        except:
            print(f'HPF type {hpf} unknown or not set - Device may need firmware update and/or HPF value set')
            print(f'Use 8206 Set ID utility to set the HPF type - HPF is typically indicated by a sticker on the box')
            print(f'If this sticker is lost, damaged, or inaccessible, contact Pinnacle with the device serial number')
        outfile = file_path + '/'+ dev_id + test1_name
        outfiles.append(outfile)

        x[1].write_read('SET LOWPASS', (CHA, test_freq + test_freq_delta) )
        x[1].write_read('SET LOWPASS', (CHB, test_freq + test_freq_delta) )
        x[1].write_read('SET LOWPASS', (CHC, test_freq + test_freq_delta) )
        data = execute_test(outfile, test_length, x[1])
        timestamps, data, fit, error = sine_fit(data, input_uV, test_freq)
        result = validate_test(fit, error, target_vals[hpf][test_number], test_freq)
        
        if result == 0:
            print(f'\nTEST SUCCESS: {dev_id}{test1_name}\n')
        else:
            print(f'\nTEST FAILED: {dev_id}{test1_name} - ERROR CODE {result}\n')
        errors.append(result)
        
        # Set up the next test
        test_number += 1
        test_freq = test_freq + (test_freq_delta * 2)
        atd.write_packet('SET FREQ', (test_freq,))
        outfile = file_path + '/'+ dev_id + test2_name
        outfiles.append(outfile)
        data = execute_test(outfile, test_length, x[1])
        timestamps, data, fit, error = sine_fit(data, 2, test_freq)
        result = validate_test(fit, error, target_vals[hpf][test_number], test_freq)
        
        if result == 0:
            print(f'\nTEST SUCCESS: {dev_id}{test2_name}\n')
        else:
            print(f'\nTEST FAILED: {dev_id}{test2_name} - ERROR CODE {result}\n')
        errors.append(result)
        
        #run the third test
        test_number += 1
        x[1].write_packet('SET LOWPASS', (CHA,test_freq + test_freq_delta) )
        x[1].write_packet('SET LOWPASS', (CHB,test_freq + test_freq_delta) )
        x[1].write_packet('SET LOWPASS', (CHC,test_freq + test_freq_delta) )
        outfile = file_path + '/'+ dev_id + test3_name
        outfiles.append(outfile)
        data = execute_test(outfile, test_length, x[1])
        timestamps, data, fit, error = sine_fit(data, input_uV, test_freq)
        result = validate_test(fit, error, target_vals[hpf][test_number], test_freq)
        
        if result == 0:
            print(f'\nTEST SUCCESS: {dev_id}{test2_name}\n')
        else:
            print(f'\nTEST FAILED: {dev_id}{test2_name} - ERROR CODE {result}\n')
        errors.append(result)
            
        if errors == [0,0,0]:
            print('\nALL TESTS COMPLETED SUCCESSFULLY\n')
        else:
            print(f'\nTEST FAILED - Errors are {errors}\n')
        
    #open the updated files in edfbrowser
    # for x in outfiles:
    #     subprocess.run(['edfbrowser', x + '.edf', montage_file])

    print("Zipping files")

    shutil.make_archive(
        file_path,              # output name (without .zip)
        "zip",                  # format
        root_dir=file_path      # folder to zip
    )

    print("Cleaning up")
    shutil.rmtree(file_path)
