variable "PUSH_BASE" {
  default = "false"
}

variable "PUSH_MINECRAFT" {
  default = "false"
}

group "default" {
  targets = ["base", "minecraft"]
}

target "base-meta" {}

target "minecraft-meta" {}

target "base" {
  inherits = ["base-meta"]
  context = "base"
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_BASE == "true" ? ["type=registry"] : ["type=cacheonly"]
}

target "minecraft" {
  inherits = ["minecraft-meta"]
  context = "minecraft"
  contexts = {
    baseimage = "target:base"
  }
  args = {
    BASE_IMAGE = "baseimage"
  }
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_MINECRAFT == "true" ? ["type=registry"] : ["type=cacheonly"]
}
