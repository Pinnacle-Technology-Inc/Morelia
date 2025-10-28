###################################
Specifics with Influx and Grafana📈
###################################

.. contents:: 

======================================
Grafana/Influx Complications 😵‍💫
======================================

Grafana and Influx are both extensive services that have their own properties and customizations available to you. This page's aim is to inform you of **important** details about each of these tools which may affect decisions in how you want to run experiments or write code. 

In our API, Grafana and Influx are both created using Docker containers, but in the case that you want to run these services independently, you will want to cater your code around this difference.

=================
Influx Details 
=================

--------------
Docker Volumes
--------------

Because Docker is creating the container for Influx, the data is stored in a Docker Volume, rather than Influx's own storage space. Depending on the sample rate of the device you are using, this data can fill up very quickly. **Please** keep in mind that if the retention policy below is not set up for your system, the disk might get filled up with time series data. 

.. image of disk 

----------------
Retention Policy
----------------

Influx has a "retention" policy that it uses in order to ensure that the computer does not fill up its entire disk space. It removes data if the data has been stored for over the set time period (i.e if the policy is set to 2 days, influx will remove data after it has become 2 days old).

Influx will remove data in batches. It does this by creating "shards", which group data together over a specific time period. For example, if the shard length is 1 hour long, then data will be grouped together in that hour and be deleted together after the time retention expiry. Shard length is determined by how long the retention policy is set to, which you can see below:

.. add image of influx's shard length to retention policy 

From Terraform, this policy can be edited inside of the ``influxdb.tf`` file, under the environment variables. By default, we set the retention policy to 47 hours, which means that the shard length is 1 hour. 

.. add image of DOCKER_INFLUXDB_INIT_RETENTION

=============================
Creating Grafana Dashboards 
=============================

During the creation of the Grafana container, Grafana looks inside of the infra/grafana/dashboards folder for json files to use as dashboards. Any json file that fits the format of a grafana dashboard here will be generated and shown on the UI. 

.. show image of the folder infra/grafana/dashboards

.. reuse image of the grafana dashboards

If you want to create your own dashboard, there is a folder where template json files are held for a basic ``8206HR`` and ``8401HR``. You can copy any of these files to the infra/grafa/dashboards folder, and edit the specifics (title, description, etc.) for your needs. 

.. Add image of the templates folder here

-------------------------------------
Customizing Dashboards for Your Needs
-------------------------------------

The json files for these dashboards can be pretty long, but upon closer inspection you can find that each part of the dashboard has its own section. For example, you can see below is the beginning and end of a single panel in the dashboard. 

.. add image of a panel in the json

.. Specifically talk about parts of the json file which are editable

At the bottom of the file, you will find a "title" line, which stores a string. Changing this string will update the title fo your dashboard.

At the top of the file, you will find a "description" line, which stores a string. Changing this string will update the description of your dashboard. 

.. incl title, description, uid, etc.

----------------------------
Automated Creation in Python
----------------------------

.. Add docs on automated creation of dashboards
