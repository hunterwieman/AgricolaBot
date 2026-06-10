#include "agricola/version.hpp"

namespace agricola {

std::string version() {
  return "agricola_cpp 0.0.1 (stage0 scaffolding; encoding=" +
         std::to_string(kEncodingVersion) +
         " data=" + std::to_string(kDataVersion) + ")";
}

}  // namespace agricola
