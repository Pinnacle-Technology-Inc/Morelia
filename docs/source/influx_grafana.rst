#####################################
Specifics with Influx and Grafana 📈
#####################################

.. contents:: 

Grafana/Influx Complications 😵‍💫
======================================

Grafana and Influx are both extensive services that have their own properties and customizations available to you. This page's aim is to inform you of **important** details about each of these tools which may affect decisions in how you want to run experiments or write code. 

In our API, Grafana and Influx are both created using Docker containers, but in the case that you want to run these services independently, you will want to cater your code around this difference.

.. _influx-label:

Influx Details 
=================

------------------
Docker Volumes 🐳
------------------

Because Docker is creating the container for Influx, the data is stored in a Docker Volume, rather than Influx's own storage space. Depending on the sample rate of the device you are using, this data can fill up very quickly. **Please** keep in mind that if the retention policy below is not set up for your system, the disk might get filled up with time series data. 

.. image of disk 
.. image:: images/disk.png
   :scale: 50%

-------------------
Retention Policy ⌛
-------------------

Influx has a "retention" policy that it uses in order to ensure that the computer does not fill up its entire disk space. It removes data if the data has been stored for over the set time period (i.e if the policy is set to 2 days, influx will remove data after it has become 2 days old).

Influx will remove data in batches. It does this by creating "shards", which group data together over a specific time period. For example, if the shard length is 1 hour long, then data will be grouped together in that hour and be deleted together after the time retention expiry. Shard length is determined by how long the retention policy is set to, which you can see below:

.. add image of influx's shard length to retention policy 
.. image:: images/shards.png
   :scale: 50%

From Terraform, this policy can be edited inside of the ``influxdb.tf`` file, under the environment variables. By default, we set the retention policy to 47 hours, which means that the shard length is 1 hour. 

.. add image of DOCKER_INFLUXDB_INIT_RETENTION
.. image:: images/retention.png
   :scale: 50%

.. _grafana-label:

Creating Grafana Dashboards 📉
===============================

During the creation of the Grafana container, Grafana looks inside of the infra/grafana/dashboards folder for json files to use as dashboards. Any json file that fits the format of a grafana dashboard here will be generated and shown on the UI. 

.. show image of the folder infra/grafana/dashboards
.. image:: images/dashboard_folder.png
   :scale: 45%

.. vertical arrow image?
.. image:: images/right_arrow.png
   :scale: 30%

.. reuse image of the grafana dashboards
.. image:: images/dashboards.png

If you want to create your own dashboard, there is a folder where template json files are held for a basic ``8206HR`` and ``8401HR``. You can copy any of these files to the infra/grafana/dashboards folder, and edit the specifics (title, description, etc.) for your needs. 

.. note:: These can be pretty finicky and need to be pretty precise.

.. Add image of the templates folder here
.. image:: images/templates.png
   :scale: 75%

----------------------------------------
Customizing Dashboards for Your Needs 🎉
----------------------------------------

Editing a Grafana dashboard is not too difficult. After loading up your dashboard on Grafana, you can change different settings of the dashbaord in the "edit" mode. To enter edit mode, just press the button in the top right corner.

.. add image of the edit button in the top right 
.. image:: images/edit_dashboard.png

After entering this mode, you are free to move panels, create new panels, and edit dashboard settings. After you are finished, you can save the dashboard by clicking the "Saved dashboard" button, and then either copying the JSON to clipboard or saving the JSON to a file. 

.. add image of saving a dashboard here 
.. image:: images/save_dashboard.png
   :scale: 50%

Placing this JSON file in the infra/grafana/dashboards folder will allow Grafana to provision it on startup, meaning that it will automatically load in the Grafana GUI (with all your changes!) when starting the container through Terraform.

Editing a Panel ⬛
-------------------

In your dashboard, you can edit panels by clicking the top right menu button on a panel, and then clicking "Edit". 

.. add image of editing a panel
.. image:: images/edit_panel.png
   :scale: 75%

Each panel queries information out of a database and can present it in variousways. If you want to edit how it queries (what information it looks for), you can change that inside of the query editor. Depending on which databse you are querying from (by default Influx), you may need to structure your query based on the query language that the database supports. 

.. add image of query area in the panel
.. image:: images/query.png
   :scale: 75%

On the right-hand side, there are settings to change how the data is displayed. By default, we set each panel to show a time series (data flowing in through time), but other options include vizualizations such as a bar chart or a table (which will show more precise timestamps). 

.. images of vizualizations
.. image:: images/vizualization_dropdown.png
   :align: center
   :scale: 97%

.. raw:: html

   <div style="height: 12px;"></div>

.. image:: images/vizualizations.png
   :align: center

Remember, after you edit the panels, if you want to save the dashboard, that you must export it as a JSON file or copy it to your clipboard (and move it somewhere else).

JSON Specifics 📁
------------------

The json files for these dashboards can be pretty long, but upon closer inspection you can find that each part of the dashboard has its own section. For example, you can see below is the beginning and end of a single panel in the dashboard. 

.. add image of a panel in the json

.. Specifically talk about parts of the json file which are editable

At the bottom of the file, you will find a "title" line, which stores a string. Changing this string will update the title fo your dashboard.

At the top of the file, you will find a "description" line, which stores a string. Changing this string will update the description of your dashboard. 

.. incl title, description, uid, etc.

-------------------------------
Automated Creation in Python 🤖
-------------------------------

.. Add docs on automated creation of dashboards
