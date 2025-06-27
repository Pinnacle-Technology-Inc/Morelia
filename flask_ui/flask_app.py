from flask import Flask, request, render_template, redirect, url_for, flash
import toml
import os
import pdb

app = Flask(__name__)
#flash in Flask needs a key to temporarily store data for this session
app.secret_key = b'_5#y2L"F4Q8z\n\ggff'


@app.route("/")
def index():
    return render_template("test.html")

@app.route("/submit", methods=["POST"])
def submit():
    #upon submission of the data, take the information and make a dictionary out of it
    data = {
        'title': 'Device Configuration File',
        'filename': request.form.get('filename'),
        'channel_names': {
            'channel_1': request.form.get('channel_1'),
            'channel_2': request.form.get('channel_2'),
            'channel_3': request.form.get('channel_3'),
        },
        'information': {
            'sample_rate': request.form.get('sample_rate'),
            'preamp_gain': request.form.get('preamp_gain'),
        },
        'channel_settings': {   
            'eeg1': request.form.get('eeg1'),
            'eeg2': request.form.get('eeg2'),
            'emg': request.form.get('emg'),
            'notch_enabled': request.form.get('notch_enabled'),
            'notch_value': request.form.get('notch_value'),
        },    
        'ttl_controls': {   
            'ttl1': {
                'output': request.form.get('ttl1_output'),
                'set_state': request.form.get('ttl_set_state'),
                'current_state': request.form.get('ttl1_current_state'),
                'rising_event': request.form.get('ttl1_rising_event'),
                'falling_event': request.form.get('ttl1_falling_event'),
                'event_comment': request.form.get('ttl1_event_comment'),
            },
            'ttl2': {
                'output': request.form.get('ttl2_output'),
                'set_state': request.form.get('ttl2_set_state'),
                'current_state': request.form.get('ttl2_current_state'),
                'rising_event': request.form.get('ttl2_rising_event'),
                'falling_event': request.form.get('ttl2_falling_event'),
                'event_comment': request.form.get('ttl2_event_comment'),
            },
            'ttl3': {
                'output': request.form.get('ttl3_output'),
                'set_state': request.form.get('ttl3_set_state'),
                'current_state': request.form.get('ttl3_current_state'),
                'rising_event': request.form.get('ttl3_rising_event'),
                'falling_event': request.form.get('ttl3_falling_event'),
                'event_comment': request.form.get('ttl3_event_comment'),
            },
            'ttl4': {
                'output': request.form.get('ttl4_output'),
                'set_state': request.form.get('ttl4_set_state'),
                'current_state': request.form.get('ttl4_current_state'),
                'rising_event': request.form.get('ttl4_rising_event'),
                'falling_event': request.form.get('ttl4_falling_event'),
                'event_comment': request.form.get('ttl4_event_comment'),
            },
            'debounce': request.form.get('debounce'),
            'synchronous': request.form.get('synchronous'),
        },

    }

    #use filename part of dictionary to create new file
    filename = request.form.get('filename')
    
    if not filename:
        filename = "default_config"

    if not filename.endswith(".toml"):
        filename += ".toml"

    if os.path.exists(filename):
        flash(f"{filename} already exists! Not overwriting")
    else:
        #create a toml dump out of the dictionary, and write it to the file
        toml_str = toml.dumps(data)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(toml_str)
        flash(f"{filename} created successfully!")

    #return to home page
    return redirect(url_for("index"))
