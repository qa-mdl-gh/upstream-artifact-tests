# mx_codegen.py (updated for PyMaterialXFormat API: readFromXmlFileBase)
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _win_add_dll_dir(d: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(d))
    else:
        os.environ["PATH"] = str(d) + ";" + os.environ.get("PATH", "")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _get_stage_source(shader, stage_name: str):
    """
    Return source for a stage without relying on a Stage enum.
    Tries:
      - shader.getStage("vertex"/"pixel").getSourceCode()
      - shader.getSourceCode("vertex"/"pixel")
      - shader.getSourceCode()  (some bindings default to pixel)
    """
    keys = [stage_name, stage_name.lower(), stage_name.upper()]

    # Try ShaderStage path: shader.getStage(name)->stage.getSourceCode()
    if hasattr(shader, "getStage"):
        for k in keys:
            try:
                st = shader.getStage(k)
                if st:
                    src = st.getSourceCode() if hasattr(st, "getSourceCode") else None
                    if src and str(src).strip():
                        return str(src)
            except Exception:
                pass

    # Try direct source query: shader.getSourceCode(name)
    if hasattr(shader, "getSourceCode"):
        for k in keys:
            try:
                src = shader.getSourceCode(k)
                if src and str(src).strip():
                    return str(src)
            except Exception:
                pass

        # Some bindings allow getSourceCode() with no args
        try:
            src = shader.getSourceCode()
            if src and str(src).strip():
                return str(src)
        except Exception:
            pass

    return None



def _read_mtlx(mxf, mx, doc, filename: Path, search_path) -> None:
    """
    PyMaterialXFormat in your build provides readFromXmlFileBase, not readFromXmlFile.
    Try a few call signatures to match the binding.
    """
    fn = str(filename)

    if hasattr(mxf, "readFromXmlFile"):
        mxf.readFromXmlFile(doc, fn)
        return

    if not hasattr(mxf, "readFromXmlFileBase"):
        raise AttributeError("Neither readFromXmlFile nor readFromXmlFileBase exists in PyMaterialXFormat")

    # Optional read options if available
    opts = None
    if hasattr(mxf, "XmlReadOptions"):
        try:
            opts = mxf.XmlReadOptions()
        except Exception:
            opts = None

    # Try common signatures
    tried = []
    for args in [
        (doc, fn),
        (doc, fn, search_path),
        (doc, fn, search_path, opts),
    ]:
        try:
            # Skip the 4-arg call if opts is None
            if len(args) == 4 and args[3] is None:
                continue
            mxf.readFromXmlFileBase(*args)
            return
        except TypeError as e:
            tried.append(str(e))
            continue

    raise TypeError(
        "Could not call readFromXmlFileBase with supported signatures. "
        "Tried: (doc, fn), (doc, fn, searchPath), (doc, fn, searchPath, options). "
        f"Errors: {tried}"
    )


def _configure_codegen_search_paths(mx, mxgen, gen, ctx, dist_root: Path, libraries_dir: Path) -> None:
    """
    Make codegen able to find target include files like:
      libraries/stdlib/genglsl/lib/mx_math.glsl
    """
    sp = mx.FileSearchPath(str(dist_root))
    sp.append(str(libraries_dir))

    # Preferred API (GenContext)
    if hasattr(ctx, "registerSourceCodeSearchPath"):
        ctx.registerSourceCodeSearchPath(sp)
        return

    # Fallback API (resolver on generator), if exposed
    if hasattr(gen, "getResolver"):
        resolver = gen.getResolver()
        if hasattr(resolver, "setSearchPath"):
            resolver.setSearchPath(sp)
            return


def _iter_surface_shader_roots(doc):
    """
    Yield (materialNode, rootElementToGenerateFrom) where rootElementToGenerateFrom
    is either a connected Output (preferred) or Node driving material.surfaceshader.
    """
    for mat in doc.getMaterialNodes():  # avoids deprecated getMaterials()
        inp = mat.getInput("surfaceshader")
        if not inp:
            continue

        out = inp.getConnectedOutput()
        if out:
            yield mat, out
            continue

        node = inp.getConnectedNode()
        if node:
            yield mat, node



def _load_libraries(mxf, mx, library_folders, search_path, lib_doc) -> None:
    """
    loadLibraries is usually present, but keep this robust just in case.
    """
    if hasattr(mxf, "loadLibraries"):
        mxf.loadLibraries(library_folders, search_path, lib_doc)
        return
    if hasattr(mxf, "loadLibrariesBase"):
        mxf.loadLibrariesBase(library_folders, search_path, lib_doc)
        return
    raise AttributeError("Neither loadLibraries nor loadLibrariesBase exists in PyMaterialXFormat")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist_root", required=True)
    ap.add_argument("--out_dir", default="mx_codegen_out")
    ap.add_argument("--targets", nargs="+", default=["glsl", "osl", "mdl"])
    args = ap.parse_args()

    dist_root = Path(args.dist_root)
    os.chdir(dist_root)
    py_root = dist_root / "python"
    bin_dir = dist_root / "bin"
    libraries_dir = dist_root / "libraries"
    materials_dir = dist_root / "resources" / "Materials"
    out_dir = Path(args.out_dir)
    targets = {t.lower() for t in args.targets}

    sys.path.insert(0, str(py_root))
    _win_add_dll_dir(bin_dir)

    import MaterialX as mx
    from MaterialX import PyMaterialXFormat as mxf
    from MaterialX import PyMaterialXGenShader as mxgen
    from MaterialX import PyMaterialXGenGlsl as mxglsl
    from MaterialX import PyMaterialXGenOsl as mxosl
    from MaterialX import PyMaterialXGenMdl as mxmdl

    print(f"dist_root:     {dist_root}")
    print(f"materials_dir: {materials_dir}")
    print(f"libraries_dir: {libraries_dir}")
    print(f"out_dir:       {out_dir}")
    print(f"targets:       {sorted(targets)}")

    # Search path used for reading (includes) and for library loading
    lib_search = mx.FileSearchPath(str(libraries_dir))

    # Load libraries once (load every subfolder under <dist_root>\libraries that contains .mtlx files)
    lib_doc = mx.createDocument()

    library_folders = []
    for d in libraries_dir.iterdir():
        if not d.is_dir():
            continue
        if any(d.rglob("*.mtlx")):
            library_folders.append(d.name)

    if not library_folders:
        raise SystemExit(f"No library folders with .mtlx found under: {libraries_dir}")

    library_folders = sorted(set(library_folders))
    _load_libraries(mxf, mx, library_folders, lib_search, lib_doc)
    print(f"Loaded libraries: {library_folders}")

    # mtlx_files = sorted(materials_dir.rglob("*.mtlx"))
    examples_dir = materials_dir / "Examples"
    if not examples_dir.exists():
        raise SystemExit(f"Examples dir not found: {examples_dir}")

    mtlx_files = sorted(examples_dir.rglob("*.mtlx"))    
    
    
    for i, doc_path in enumerate(mtlx_files, 1):
        print(f"[{i}/{len(mtlx_files)}] {doc_path}")

        doc = mx.createDocument()

        # Per-document search path: material folder first, then libraries
        read_search = mx.FileSearchPath(str(doc_path.parent))
        read_search.append(str(libraries_dir))

        _read_mtlx(mxf, mx, doc, doc_path, read_search)
        doc.importLibrary(lib_doc)

        def _validate(doc):
            # Newer/pybind-style: returns (bool, str)
            try:
                ok, msg = doc.validate()
                return ok, msg
            except TypeError:
                # Older style (if you ever hit it): validate() -> bool
                ok = doc.validate()
                return bool(ok), ""

        ok, err = _validate(doc)
        if not ok:
            print(f"  [WARN] validate() failed:\n{err}\n")

        roots = list(_iter_surface_shader_roots(doc))
        if not roots:
            print("  [SKIP] no material surfaceshader connections")
            continue

        rel_folder = doc_path.parent.relative_to(materials_dir)
        file_base = doc_path.stem

        for mat, root in roots:
            mat_name = mat.getName() or "Material"
            shader_name = f"{file_base}__{mat_name}"

            # GLSL
            if "glsl" in targets:
                gen = mxglsl.GlslShaderGenerator.create()
                ctx = mxgen.GenContext(gen)
                shader = gen.generate(shader_name, root, ctx)

            if "glsl" in targets:
                gen = mxglsl.GlslShaderGenerator.create()
                ctx = mxgen.GenContext(gen)
                _configure_codegen_search_paths(mx, mxgen, gen, ctx, dist_root, libraries_dir)
                shader = gen.generate(shader_name, root, ctx)

                vsrc = _get_stage_source(shader, "vertex")
                psrc = _get_stage_source(shader, "pixel")

                out_base = out_dir / "glsl" / rel_folder / shader_name
                if vsrc:
                    _write_text(out_base.with_suffix(".vert"), vsrc)
                if psrc:
                    _write_text(out_base.with_suffix(".frag"), psrc)

            if "osl" in targets:
                gen = mxosl.OslShaderGenerator.create()
                ctx = mxgen.GenContext(gen)
                _configure_codegen_search_paths(mx, mxgen, gen, ctx, dist_root, libraries_dir)
                shader = gen.generate(shader_name, root, ctx)

                psrc = _get_stage_source(shader, "pixel")
                if psrc:
                    _write_text(out_dir / "osl" / rel_folder / f"{shader_name}.osl", psrc)

            if "mdl" in targets:
                gen = mxmdl.MdlShaderGenerator.create()
                ctx = mxgen.GenContext(gen)
                _configure_codegen_search_paths(mx, mxgen, gen, ctx, dist_root, libraries_dir)
                shader = gen.generate(shader_name, root, ctx)

                psrc = _get_stage_source(shader, "pixel")
                if psrc:
                    _write_text(out_dir / "mdl" / rel_folder / f"{shader_name}.mdl", psrc)

    print("Done.")


if __name__ == "__main__":
    main()