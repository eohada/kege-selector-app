{ pkgs ? import <nixpkgs> {} }:

let
  my-python = pkgs.python311.withPackages (ps: with ps; [
    requests
    numpy
    flask
    flask-cors
  ]);
in
pkgs.mkShell {
  packages = [
    my-python
    pkgs.libGL
    pkgs.glib
    pkgs.stdenv.cc.cc.lib
    pkgs.zlib
    pkgs.xorg.libX11
  ];

  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.libGL}/lib:${pkgs.glib.out}/lib:${pkgs.zlib}/lib:${pkgs.xorg.libX11}/lib:$LD_LIBRARY_PATH"
    
    python -m venv --system-site-packages .venv
    export PATH="$PWD/.venv/bin:$PATH"
    
    pip install opencv-python-headless==4.10.0.84 > /dev/null 2>&1
    echo "QA Companion Daemon Env Loaded! (No UI needed)"
  '';
}
