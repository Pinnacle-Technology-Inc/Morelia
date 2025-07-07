from flask import Flask, request, render_template, redirect, url_for, flash, session
import toml
import os
import pdb
from werkzeug.utils import secure_filename

app = Flask(__name__)
#flash in Flask needs a key to temporarily store data for this session
app.secret_key = b'_5#y2L"F4Q8z\c\ggff'

@app.route("/")
def homepage():
    return render_template("index.html")

@app.route("/Experiment_Config")
def exp_config():
    return render_template("exp_config.html")

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
        elif "Experiment" in title:
            return redirect(url_for("exp_config"))
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
        #no file was loaded — treat as new file
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
        #no file was loaded — treat as new file
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
        #no file was loaded — treat as new file
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
        #no file was loaded — treat as new file
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
        #no file was loaded — treat as new file
        if os.path.exists(filename):
            flash(f"{filename} already exists! Please choose a new name.", "error")
        else:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} created successfully!", "success")

    session.pop("loaded_filename", None)
    return redirect(url_for("page5"))


#Experiment Config. Form
@app.route("/submit_exp", methods=["POST"])
def submit_exp():
    session.pop("loaded_config", None)

    experiment_name = request.form.get("filename") or "default-experiment"
    folder_name = f"{experiment_name}_folder"

    os.makedirs(folder_name, exist_ok=True)

    # Validate devices
    device_names = request.form.getlist("device_name[]")
    config_files = request.files.getlist("config_file[]")
    device_types = request.form.getlist("device_type[]")
    device_ports = request.form.getlist("device_port[]")
    placeholder_1 = request.form.getlist("placeholder1[]")
    placeholder_4 = request.form.getlist("placeholder4[]")

    if not device_names or all(name.strip() == "" for name in device_names):
        flash("At least one device must be submitted.", "error")
        return render_template("exp_config.html", retain_form=True, form_data=request.form)

    devices = []
    for i in range(len(device_names)):
        if i >= len(config_files) or not config_files[i] or config_files[i].filename.strip() == "":
            flash(f"No configuration file uploaded for device {device_names[i] or 'unnamed device'}.", "error")
            return render_template("exp_config.html", retain_form=True, form_data=request.form)

        file_obj = config_files[i]
        config_filename = secure_filename(file_obj.filename)
        config_path = os.path.join(folder_name, config_filename)
        file_obj.save(config_path)

        devices.append({
            "device_name": device_names[i],
            "config_file": config_filename,
            "device_type": device_types[i],
            "device_port": device_ports[i],
            "placeholder_1": placeholder_1[i],
            "placeholder_2": "true" if f"PH2_{i}" in request.form else "false",
            "placeholder_3": "true" if f"PH3_{i}" in request.form else "false",
            "placeholder_4": placeholder_4[i],
        })

    # Save experiment .toml file inside the folder
    config_data = {
        "title": "Experiment Configuration File",
        "experiment_name": experiment_name,
        "devices": devices
    }

    exp_file_path = os.path.join(folder_name, f"{experiment_name}.toml")
    if os.path.exists(exp_file_path):
        flash(f"Experiment file {experiment_name}.toml already exists in {folder_name}.", "error")
        return render_template("exp_config.html", retain_form=True, form_data=request.form)

    with open(exp_file_path, "w", encoding="utf-8") as f:
        f.write(toml.dumps(config_data))

    flash(f"Experiment saved successfully to {exp_file_path}!", "success")
    
    toml_files = [f for f in os.listdir(folder_name) if f.endswith(".toml")]
    return render_template("exp_config.html", retain_form=True, form_data=request.form, toml_files=toml_files, current_folder=folder_name)

    return redirect(url_for("exp_config"))

@app.route("/upload_file_to_folder", methods=["POST"])
def upload_file_to_folder():
    uploaded_file = request.files.get("file")
    folder = request.form.get("folder")

    if uploaded_file and uploaded_file.filename.endswith(".toml"):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, secure_filename(uploaded_file.filename))
        uploaded_file.save(path)
        flash(f"{uploaded_file.filename} uploaded to {folder}", "success")
    else:
        flash("Only .toml files are allowed", "error")

    return redirect(url_for("exp_config"))

@app.route("/exp_config_upload_config_file", methods=["POST"])
def exp_config_upload_config_file():
    uploaded_file = request.files.get("config_file")
    experiment_name = request.form.get("filename") or "default-experiment"
    folder = f"{experiment_name}_folder"
    os.makedirs(folder, exist_ok=True)

    if uploaded_file and uploaded_file.filename.endswith(".toml"):
        filename = secure_filename(uploaded_file.filename)
        save_path = os.path.join(folder, filename)
        uploaded_file.save(save_path)
        flash(f"{filename} uploaded to {folder}", "success")
    else:
        flash("Invalid file. Please upload a .toml file.", "error")

    return redirect(url_for("exp_config"))
