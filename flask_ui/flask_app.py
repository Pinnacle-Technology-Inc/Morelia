from flask import Flask, request, render_template, redirect, url_for, flash, session
import toml
import os
import pdb

app = Flask(__name__)
#flash in Flask needs a key to temporarily store data for this session
app.secret_key = b'_5#y2L"F4Q8z\c\ggff'

@app.route("/")
def homepage():
    return render_template("index.html")


@app.route("/Pod8206HR")
def page1():
    return render_template("Pod8206HR.html")

@app.route("/Pod8229")
def page2():
    return render_template("Pod8229.html")

@app.route("/Pod8274D")
def page3():
    return render_template("Pod8274D.html")

@app.route("/Pod8401HR")
def page4():
    return render_template("Pod8401HR.html")

@app.route("/Pod8480SC")
def page5():
    return render_template("Pod8480SC.html")

@app.route("/load_config", methods=["POST"])
def upload_config():
    uploaded_file = request.files.get("config_file")
    if not uploaded_file or uploaded_file.filename == "":
        flash("No file selected!", "error")
        return redirect(url_for("homepage"))

    try:
        config_data = toml.loads(uploaded_file.read().decode("utf-8"))
        session["loaded_config"] = config_data  # Store config in session
        # redirect to correct form page based on title
        session["loaded_filename"] = uploaded_file.filename
        title = config_data.get("title", "")
        if "8206HR" in title:
            return redirect(url_for("page1"))
        elif "8229" in title:
            return redirect(url_for("page2"))
        elif "8274D" in title:
            return redirect(url_for("page3"))
        elif "8401HR" in title:
            return redirect(url_for("page4"))
        elif "8480SC" in title:
            return redirect(url_for("page5"))
        else:
            flash("Unknown device type in configuration file.", "error")
            return redirect(url_for("homepage"))
    except Exception as e:
        flash(f"Failed to load configuration: {str(e)}", "error")
        return redirect(url_for("homepage"))

#Pod8206HR Form
@app.route("/submit1", methods=["POST"])
def submit1():
    session.pop("loaded_config", None)
    
    if "loaded_config" in session:
        print("Session still has loaded_config")
    else:
        print("Session does NOT have loaded_config")
    
    #upon submission of the data, take the information and make a dictionary out of it
    data = {
        'title': 'Pod8206HR Device Configuration File',
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
            'notch_value' : request.form.get('notch_value'),
        },    
        'ttl_controls': {   
            'ttl1': {
                'output': request.form.get('ttl1_output'),
                'set_state': request.form.get('ttl1_set_state'),
                'current_state': request.form.get('ttl1_set_current_state'),
                'rising_event': request.form.get('ttl1_rising_event'),
                'falling_event': request.form.get('ttl1_falling_event'),
                'event_comment': request.form.get('ttl1_event_comment'),
            },
            'ttl2': {
                'output': request.form.get('ttl2_output'),
                'set_state': request.form.get('ttl2_set_state'),
                'current_state': request.form.get('ttl2_set_current_state'),
                'rising_event': request.form.get('ttl2_rising_event'),
                'falling_event': request.form.get('ttl2_falling_event'),
                'event_comment': request.form.get('ttl2_event_comment'),
            },
            'ttl3': {
                'output': request.form.get('ttl3_output'),
                'set_state': request.form.get('ttl3_set_state'),
                'current_state': request.form.get('ttl3_set_current_state'),
                'rising_event': request.form.get('ttl3_rising_event'),
                'falling_event': request.form.get('ttl3_falling_event'),
                'event_comment': request.form.get('ttl3_event_comment'),
            },
            'ttl4': {
                'output': request.form.get('ttl4_output'),
                'set_state': request.form.get('ttl4_set_state'),
                'current_state': request.form.get('ttl4_set_current_state'),
                'rising_event': request.form.get('ttl4_rising_event'),
                'falling_event': request.form.get('ttl4_falling_event'),
                'event_comment': request.form.get('ttl4_event_comment'),
            },

            'debounce': request.form.get('debounce'),
            'synchronous': request.form.get('synchronous'),
        },

    }

    #use filename part of dictionary to create new file
    filename = request.form.get('filename') or "default_config"
    if not filename.endswith(".toml"):
        filename += ".toml"

    loaded_filename = session.get("loaded_filename")

    if loaded_filename:
        if filename == loaded_filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} updated successfully!", "success")
        else:
            if os.path.exists(filename):
                flash(f"{filename} already exists! Please choose a new name.", "error")
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(toml.dumps(data))
                flash(f"{filename} created successfully!", "success")
    else:
        # No file was loaded — treat as new file
        if os.path.exists(filename):
            flash(f"{filename} already exists! Please choose a new name.", "error")
        else:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} created successfully!", "success")

    session.pop("loaded_filename", None)
    return redirect(url_for("page1"))

#Pod8229 Form
@app.route("/submit2", methods=["POST"])
def submit2():
    session.pop("loaded_config", None)
    #upon submission of the data, take the information and make a dictionary out of it
    data = {
        'title': 'Pod8229 Device Configuration File',
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
            'notch_value' : request.form.get('notch_value'),
        },    
        'ttl_controls': {   
            'ttl1': {
                'output': request.form.get('ttl1_output'),
                'set_state': request.form.get('ttl1_set_state'),
                'current_state': request.form.get('ttl1_set_current_state'),
                'rising_event': request.form.get('ttl1_rising_event'),
                'falling_event': request.form.get('ttl1_falling_event'),
                'event_comment': request.form.get('ttl1_event_comment'),
            },
            'ttl2': {
                'output': request.form.get('ttl2_output'),
                'set_state': request.form.get('ttl2_set_state'),
                'current_state': request.form.get('ttl2_set_current_state'),
                'rising_event': request.form.get('ttl2_rising_event'),
                'falling_event': request.form.get('ttl2_falling_event'),
                'event_comment': request.form.get('ttl2_event_comment'),
            },
            'ttl3': {
                'output': request.form.get('ttl3_output'),
                'set_state': request.form.get('ttl3_set_state'),
                'current_state': request.form.get('ttl3_set_current_state'),
                'rising_event': request.form.get('ttl3_rising_event'),
                'falling_event': request.form.get('ttl3_falling_event'),
                'event_comment': request.form.get('ttl3_event_comment'),
            },
            'ttl4': {
                'output': request.form.get('ttl4_output'),
                'set_state': request.form.get('ttl4_set_state'),
                'current_state': request.form.get('ttl4_set_current_state'),
                'rising_event': request.form.get('ttl4_rising_event'),
                'falling_event': request.form.get('ttl4_falling_event'),
                'event_comment': request.form.get('ttl4_event_comment'),
            },

            'debounce': request.form.get('debounce'),
            'synchronous': request.form.get('synchronous'),
        },

    }

    #use filename part of dictionary to create new file
    filename = request.form.get('filename') or "default_config"
    if not filename.endswith(".toml"):
        filename += ".toml"

    loaded_filename = session.get("loaded_filename")

    if loaded_filename:
        if filename == loaded_filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} updated successfully!", "success")
        else:
            if os.path.exists(filename):
                flash(f"{filename} already exists! Please choose a new name.", "error")
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(toml.dumps(data))
                flash(f"{filename} created successfully!", "success")
    else:
        # No file was loaded — treat as new file
        if os.path.exists(filename):
            flash(f"{filename} already exists! Please choose a new name.", "error")
        else:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} created successfully!", "success")

    session.pop("loaded_filename", None)
    return redirect(url_for("page2"))

#Pod8274D Form
@app.route("/submit3", methods=["POST"])
def submit3():
    session.pop("loaded_config", None)
    #upon submission of the data, take the information and make a dictionary out of it
    data = {
        'title': 'Pod8274D Device Configuration File',
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
            'notch_value' : request.form.get('notch_value'),
        },    
        'ttl_controls': {   
            'ttl1': {
                'output': request.form.get('ttl1_output'),
                'set_state': request.form.get('ttl1_set_state'),
                'current_state': request.form.get('ttl1_set_current_state'),
                'rising_event': request.form.get('ttl1_rising_event'),
                'falling_event': request.form.get('ttl1_falling_event'),
                'event_comment': request.form.get('ttl1_event_comment'),
            },
            'ttl2': {
                'output': request.form.get('ttl2_output'),
                'set_state': request.form.get('ttl2_set_state'),
                'current_state': request.form.get('ttl2_set_current_state'),
                'rising_event': request.form.get('ttl2_rising_event'),
                'falling_event': request.form.get('ttl2_falling_event'),
                'event_comment': request.form.get('ttl2_event_comment'),
            },
            'ttl3': {
                'output': request.form.get('ttl3_output'),
                'set_state': request.form.get('ttl3_set_state'),
                'current_state': request.form.get('ttl3_set_current_state'),
                'rising_event': request.form.get('ttl3_rising_event'),
                'falling_event': request.form.get('ttl3_falling_event'),
                'event_comment': request.form.get('ttl3_event_comment'),
            },
            'ttl4': {
                'output': request.form.get('ttl4_output'),
                'set_state': request.form.get('ttl4_set_state'),
                'current_state': request.form.get('ttl4_set_current_state'),
                'rising_event': request.form.get('ttl4_rising_event'),
                'falling_event': request.form.get('ttl4_falling_event'),
                'event_comment': request.form.get('ttl4_event_comment'),
            },

            'debounce': request.form.get('debounce'),
            'synchronous': request.form.get('synchronous'),
        },

    }

    #use filename part of dictionary to create new file
    filename = request.form.get('filename') or "default_config"
    if not filename.endswith(".toml"):
        filename += ".toml"

    loaded_filename = session.get("loaded_filename")

    if loaded_filename:
        if filename == loaded_filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} updated successfully!", "success")
        else:
            if os.path.exists(filename):
                flash(f"{filename} already exists! Please choose a new name.", "error")
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(toml.dumps(data))
                flash(f"{filename} created successfully!", "success")
    else:
        # No file was loaded — treat as new file
        if os.path.exists(filename):
            flash(f"{filename} already exists! Please choose a new name.", "error")
        else:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} created successfully!", "success")

    session.pop("loaded_filename", None)
    return redirect(url_for("page3"))

#Pod8401HR Form
@app.route("/submit4", methods=["POST"])
def submit4():
    session.pop("loaded_config", None)
    #upon submission of the data, take the information and make a dictionary out of it
    data = {
        'title': 'Pod8401HR Device Configuration File',
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
            'notch_value' : request.form.get('notch_value'),
        },    
        'ttl_controls': {   
            'ttl1': {
                'output': request.form.get('ttl1_output'),
                'set_state': request.form.get('ttl1_set_state'),
                'current_state': request.form.get('ttl1_set_current_state'),
                'rising_event': request.form.get('ttl1_rising_event'),
                'falling_event': request.form.get('ttl1_falling_event'),
                'event_comment': request.form.get('ttl1_event_comment'),
            },
            'ttl2': {
                'output': request.form.get('ttl2_output'),
                'set_state': request.form.get('ttl2_set_state'),
                'current_state': request.form.get('ttl2_set_current_state'),
                'rising_event': request.form.get('ttl2_rising_event'),
                'falling_event': request.form.get('ttl2_falling_event'),
                'event_comment': request.form.get('ttl2_event_comment'),
            },
            'ttl3': {
                'output': request.form.get('ttl3_output'),
                'set_state': request.form.get('ttl3_set_state'),
                'current_state': request.form.get('ttl3_set_current_state'),
                'rising_event': request.form.get('ttl3_rising_event'),
                'falling_event': request.form.get('ttl3_falling_event'),
                'event_comment': request.form.get('ttl3_event_comment'),
            },
            'ttl4': {
                'output': request.form.get('ttl4_output'),
                'set_state': request.form.get('ttl4_set_state'),
                'current_state': request.form.get('ttl4_set_current_state'),
                'rising_event': request.form.get('ttl4_rising_event'),
                'falling_event': request.form.get('ttl4_falling_event'),
                'event_comment': request.form.get('ttl4_event_comment'),
            },

            'debounce': request.form.get('debounce'),
            'synchronous': request.form.get('synchronous'),
        },

    }

    #use filename part of dictionary to create new file
    filename = request.form.get('filename') or "default_config"
    if not filename.endswith(".toml"):
        filename += ".toml"

    loaded_filename = session.get("loaded_filename")

    if loaded_filename:
        if filename == loaded_filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} updated successfully!", "success")
        else:
            if os.path.exists(filename):
                flash(f"{filename} already exists! Please choose a new name.", "error")
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(toml.dumps(data))
                flash(f"{filename} created successfully!", "success")
    else:
        # No file was loaded — treat as new file
        if os.path.exists(filename):
            flash(f"{filename} already exists! Please choose a new name.", "error")
        else:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} created successfully!", "success")

    session.pop("loaded_filename", None)
    return redirect(url_for("page4"))

#Pod8480SC Form
@app.route("/submit5", methods=["POST"])
def submit5():
    session.pop("loaded_config", None)
    #upon submission of the data, take the information and make a dictionary out of it
    data = {
        'title': 'Pod8480SC Device Configuration File',
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
            'notch_value' : request.form.get('notch_value'),
        },    
        'ttl_controls': {   
            'ttl1': {
                'output': request.form.get('ttl1_output'),
                'set_state': request.form.get('ttl1_set_state'),
                'current_state': request.form.get('ttl1_set_current_state'),
                'rising_event': request.form.get('ttl1_rising_event'),
                'falling_event': request.form.get('ttl1_falling_event'),
                'event_comment': request.form.get('ttl1_event_comment'),
            },
            'ttl2': {
                'output': request.form.get('ttl2_output'),
                'set_state': request.form.get('ttl2_set_state'),
                'current_state': request.form.get('ttl2_set_current_state'),
                'rising_event': request.form.get('ttl2_rising_event'),
                'falling_event': request.form.get('ttl2_falling_event'),
                'event_comment': request.form.get('ttl2_event_comment'),
            },
            'ttl3': {
                'output': request.form.get('ttl3_output'),
                'set_state': request.form.get('ttl3_set_state'),
                'current_state': request.form.get('ttl3_set_current_state'),
                'rising_event': request.form.get('ttl3_rising_event'),
                'falling_event': request.form.get('ttl3_falling_event'),
                'event_comment': request.form.get('ttl3_event_comment'),
            },
            'ttl4': {
                'output': request.form.get('ttl4_output'),
                'set_state': request.form.get('ttl4_set_state'),
                'current_state': request.form.get('ttl4_set_current_state'),
                'rising_event': request.form.get('ttl4_rising_event'),
                'falling_event': request.form.get('ttl4_falling_event'),
                'event_comment': request.form.get('ttl4_event_comment'),
            },
            'debounce': request.form.get('debounce'),
            'synchronous': request.form.get('synchronous'),
        },

    }

    #use filename part of dictionary to create new file
    filename = request.form.get('filename') or "default_config"
    if not filename.endswith(".toml"):
        filename += ".toml"

    loaded_filename = session.get("loaded_filename")

    if loaded_filename:
        if filename == loaded_filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} updated successfully!", "success")
        else:
            if os.path.exists(filename):
                flash(f"{filename} already exists! Please choose a new name.", "error")
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(toml.dumps(data))
                flash(f"{filename} created successfully!", "success")
    else:
        # No file was loaded — treat as new file
        if os.path.exists(filename):
            flash(f"{filename} already exists! Please choose a new name.", "error")
        else:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} created successfully!", "success")

    session.pop("loaded_filename", None)
    return redirect(url_for("page5"))
