###########################################
Visualizing Data During Streams 😎
###########################################

.. TODO: You cant use commands when streaming, you have to stop streaming.

.. contents:: 

======================
The Terraform Automation 🗻
======================

If you downloaded Morelia directly from the GitHub page, you'll have access to visualize the data streamed to the ``InfluxSink`` and ``QuestSink`` through Grafana.

In order to do so, you'll need to download both Terraform and Docker to create containers for both the data source (Influx or Quest) and Grafana. The downloads can be found at the links below, or if you are on bash, you can follow the bash section to quickly download and setup the architecture.

Once downloaded, inside of the 'infra' directory, you can use ``terraform init`` to initialize the Terraform configuration, and ``terraform apply`` to begin the infrastructure.



======================
Bash Shell Script
======================
For ease of use, we have included a bash shell script that downloads Terraform and Docker, and then uses them to create containers for a datasource of your choice and Grafana. A 


---------------------
Infinite Streaming 🌌
---------------------

