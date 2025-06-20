resource "docker_container" "questdb" {
  count = var.use_questdb ? 1 : 0

  name  = "questdb"
  image = "questdb/questdb:8.3.3"

  ports {
    internal = 9000
    external = var.questdb_ui_port
  }

  ports {
    internal = 8812
    external = var.questdb_pg_port
  }

  ports {
    internal = 9009
    external = var.questdb_ilp_port
  }

  networks_advanced {
    name = docker_network.monitoring.name
  	aliases = ["questdb"]
  }

  env = [
    "QDB_PG_USER=${var.questdb_admin_user}",
    "QDB_PG_PASSWORD=${var.questdb_admin_password}",
    "QDB_PG_ENABLED=true",
    "QDB_PG_READONLY_USER_ENABLED=false"
  ]
}
