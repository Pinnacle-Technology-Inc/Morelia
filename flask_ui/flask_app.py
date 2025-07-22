from flask import Flask, request, render_template, redirect, url_for, flash, session
import toml
import os
import shutil
from werkzeug.utils import secure_filename

app = Flask(__name__)
#flash in Flask needs a key to temporarily store data for this session
app.secret_key = b'_5#y2L"F4Q8zww\ggff'

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
        filename = uploaded_file.filename
        filepath = os.path.join(os.getcwd(), filename)

        # Save uploaded file to disk immediately
        uploaded_file.save(filepath)

        # Load config from the saved file on disk
        with open(filepath, "r", encoding="utf-8") as f:
            config_data = toml.load(f)

        # Save in session for editing/saving later
        session["loaded_config"] = config_data
        session["loaded_filename"] = filename

        # Redirect to correct form
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


@app.route("/clear_config", methods=["POST"])
def clear_config():
    session.pop("loaded_config", None)
    session.pop("loaded_filename", None)
    flash("Configuration cleared.")
    return redirect(request.referrer or url_for("homepage"))

#Pod8206HR Form
@app.route("/submit1", methods=["POST"])
def submit1():
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
            'aux_input': request.form.get('aux_input'),
        },
        'channel_settings': {
            'eeg1': request.form.get('eeg1'),
            'eeg2': request.form.get('eeg2'),
            'emg': request.form.get('emg'),
            'ecg': request.form.get('ecg'),
            'accel': request.form.get('accel'),
            'notch_enabled': request.form.get('notch_enabled'),
            'notch_value': request.form.get('notch_value'),
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
        if os.path.exists(filename):
            flash(f"{filename} already exists! Please choose a new name.", "error")
        else:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(toml.dumps(data))
            flash(f"{filename} created successfully!", "success")

    session.pop("loaded_filename", None)
    session.pop("loaded_config", None)

    return redirect(url_for("page1"))


#Pod8229 Form
@app.route("/submit2", methods=["POST"])
def submit2():

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
    session.pop("loaded_config", None)
    return redirect(url_for("page2"))

#Pod8274D Form
@app.route("/submit3", methods=["POST"])
def submit3():

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
    session.pop("loaded_config", None)
    return redirect(url_for("page3"))

#Pod8401HR Form
@app.route("/submit4", methods=["POST"])
def submit4():

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
    session.pop("loaded_config", None)
    return redirect(url_for("page4"))

#Pod8480SC Form
@app.route("/submit5", methods=["POST"])
def submit5():

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
    session.pop("loaded_config", None)
    return redirect(url_for("page5"))

# Experiment Config. Form
# Save a single TOML file to the given folder
def save_toml_file_to_folder(file, folder):
    os.makedirs(folder, exist_ok=True)
    if file and file.filename.endswith(".toml"):
        filename = secure_filename(file.filename)
        path = os.path.join(folder, filename)
        file.save(path)
        return filename, path
    return None, None

# Extract device type from title field in TOML
def extract_device_type_from_title(title):
    if "Device Configuration File" in title:
        return title.split("Device Configuration File")[0].strip()
    return title.strip()

@app.route("/submit_exp", methods=["POST"])
def submit_exp():
    loaded_filename = session.get("loaded_filename")

    experiment_name = request.form.get("filename", "default-experiment").strip()
    folder_name = request.form.get("folder", "").strip()
    if not folder_name:
        folder_name = session.get("loaded_config", {}).get("folder_name", "")
    if not folder_name:
        folder_name = f"{experiment_name}_folder"
    os.makedirs(folder_name, exist_ok=True)

    device_names = request.form.getlist("device_name[]")
    new_config_files = request.files.getlist("config_file_new[]")
    existing_config_files = request.form.getlist("config_file_existing[]")
    device_types = request.form.getlist("device_type[]")
    device_ports = request.form.getlist("device_port[]")
    placeholder_1 = request.form.getlist("placeholder1[]")
    placeholder_4 = request.form.getlist("placeholder4[]")

    # Validate device types
    invalid_types = [dt for dt in device_types if dt.strip() == "" or dt == "null"]
    if invalid_types:
        flash("Every device must have a device type.", "error")
        return render_template("exp_config.html",
                               retain_form=True,
                               form_data=dict(request.form),
                               current_folder=folder_name)

    if not device_names or all(name.strip() == "" for name in device_names):
        flash("At least one device must be submitted.", "error")
        return render_template("exp_config.html",
                               retain_form=True,
                               form_data=dict(request.form),
                               current_folder=folder_name)

    devices = []
    for i, name in enumerate(device_names):
        name = name.strip() or f"Pod_{i+1}"

        # Uploaded file for this device row (may be empty)
        file_obj = new_config_files[i] if i < len(new_config_files) else None

        # Default to existing config filename if no new file
        config_filename = existing_config_files[i] if i < len(existing_config_files) else ""

        inferred_type = device_types[i].strip() if i < len(device_types) else ""

        if file_obj and file_obj.filename.strip():
            # Save uploaded config file
            saved_filename, saved_path = save_toml_file_to_folder(file_obj, folder_name)
            if saved_filename:
                config_filename = saved_filename

                # Try to infer device type from uploaded file content
                try:
                    with open(saved_path, "r", encoding="utf-8") as f:
                        parsed = toml.load(f)
                        title = parsed.get("title", "")
                        inferred_type = extract_device_type_from_title(title) or inferred_type
                except Exception as e:
                    flash(f"Error parsing {saved_filename}: {str(e)}", "error")
                    # fallback keep inferred_type as is

        else:
            # No new uploaded file, try copy from previous folder if different
            if config_filename:
                previous_folder = request.form.get("previous_folder", "").strip()
                if previous_folder and previous_folder != folder_name:
                    src_path = os.path.join(previous_folder, config_filename)
                    dst_path = os.path.join(folder_name, config_filename)
                    if os.path.exists(src_path) and not os.path.exists(dst_path):
                        try:
                            shutil.copy2(src_path, dst_path)
                        except Exception as e:
                            flash(f"Failed to copy config file for device '{name}': {e}", "error")

            if not config_filename:
                flash(f"No configuration file uploaded or found for device '{name}'.", "error")
                return render_template("exp_config.html",
                                       retain_form=True,
                                       form_data=dict(request.form),
                                       current_folder=folder_name)

        placeholder_2_val = "true" if request.form.get(f"PH2_{i}") == "true" else "false"
        placeholder_3_val = "true" if request.form.get(f"PH3_{i}") == "true" else "false"

        devices.append({
            "device_name": name,
            "config_file": config_filename,
            "device_type": inferred_type,
            "device_port": device_ports[i] if i < len(device_ports) else "",
            "placeholder_1": placeholder_1[i] if i < len(placeholder_1) else "",
            "placeholder_2": placeholder_2_val,
            "placeholder_3": placeholder_3_val,
            "placeholder_4": placeholder_4[i] if i < len(placeholder_4) else "",
        })

    # Save experiment config TOML file
    exp_filename = f"{experiment_name}.toml"
    exp_file_path = os.path.join(folder_name, exp_filename)

    # Check if overwriting same file in same folder or new file
    if os.path.exists(exp_file_path):
        if exp_filename == loaded_filename and folder_name == session.get("loaded_config", {}).get("folder_name"):
            # Overwrite safely
            with open(exp_file_path, "w", encoding="utf-8") as f:
                f.write(toml.dumps({
                    "title": "Experiment Configuration File",
                    "folder_name": folder_name,
                    "experiment_name": experiment_name,
                    "devices": devices
                }))
            flash(f"{exp_filename} updated successfully in {folder_name}!", "success")
        else:
            flash(f"{exp_filename} already exists in {folder_name}! Please choose a different name or folder.", "error")
            return render_template("exp_config.html",
                                   retain_form=True,
                                   form_data=dict(request.form),
                                   current_folder=folder_name)
    else:
        # New save
        with open(exp_file_path, "w", encoding="utf-8") as f:
            f.write(toml.dumps({
                "title": "Experiment Configuration File",
                "folder_name": folder_name,
                "experiment_name": experiment_name,
                "devices": devices
            }))
        flash(f"{exp_filename} saved successfully in {folder_name}!", "success")

    # Clear session loaded config and filename after save
    session.pop("loaded_filename", None)
    session.pop("loaded_config", None)

    # List all toml files in folder to show in template
    toml_files = [f for f in os.listdir(folder_name) if f.endswith(".toml")]

    return render_template("exp_config.html",
                           devices=devices,
                           retain_form=True,
                           form_data=dict(request.form),
                           toml_files=toml_files,
                           current_folder=folder_name)
# Debugging Purposes
if __name__ == "__main__":
    app.run(debug=True)
