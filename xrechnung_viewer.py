import os
import sys
import tempfile
import subprocess
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_file

try:
    from lxml import etree
except ImportError:
    print("ERROR: lxml not installed. Run: pip install lxml")
    sys.exit(1)

try:
    from saxonche import PySaxonProcessor
except ImportError:
    print("ERROR: saxonche not installed. Run: pip install saxonche")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent.resolve()
app = Flask(
    __name__,
    template_folder=SCRIPT_DIR / "templates",
    static_folder=SCRIPT_DIR / "static",
)

XSL_DIR = SCRIPT_DIR / "3rdparty" / "xrechnung-visualization" / "src" / "xsl"
FOP_HOME = SCRIPT_DIR / "lib" / "fop"
FOP_CONFIG = SCRIPT_DIR / "3rdparty" / "xrechnung-visualization" / "conf" / "fop.xconf"
FONTS_DIR = SCRIPT_DIR / "3rdparty" / "xrechnung-visualization" / "conf" / "fonts"


def find_fop():
    fop_jar = FOP_HOME / "fop.jar"
    if fop_jar.exists():
        return fop_jar
    return None


def find_java():
    java_cmd = shutil.which("java")
    if java_cmd:
        return java_cmd

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        java_exe = Path(java_home) / "bin" / "java"
        if java_exe.exists():
            return str(java_exe)

    return None


def generate_fop_config():
    """Generate FOP config with absolute font paths to avoid path resolution issues"""
    fonts_url = FONTS_DIR.resolve().as_uri()

    config_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<fop version="1.0">
  <accessibility>true</accessibility>
  <renderers>
    <renderer mime="application/pdf">
      <fonts>
        <font kerning="yes" embed-url="{fonts_url}/SourceSerifPro-Light.ttf" embedding-mode="subset">
          <font-triplet name="SourceSerifPro" style="normal" weight="normal"/>
        </font>
        <font kerning="yes" embed-url="{fonts_url}/SourceSerifPro-SemiBold.ttf" embedding-mode="subset">
          <font-triplet name="SourceSerifPro" style="normal" weight="bold"/>
        </font>
        <font kerning="yes" embed-url="{fonts_url}/SourceSerifPro-LightItalic.ttf" embedding-mode="subset">
          <font-triplet name="SourceSerifPro" style="italic" weight="normal"/>
        </font>
        <font kerning="yes" embed-url="{fonts_url}/SourceSerifPro-SemiBoldItalic.ttf" embedding-mode="subset">
          <font-triplet name="SourceSerifPro" style="italic" weight="bold"/>
        </font>
      </fonts>
    </renderer>
  </renderers>
</fop>
"""
    return config_xml


FOP_JAR = find_fop()
JAVA_CMD = find_java()
HAS_FOP = FOP_JAR is not None and JAVA_CMD is not None

if HAS_FOP:
    print(f"Apache FOP found: {FOP_JAR}")
    print(f"Java found: {JAVA_CMD}")
else:
    if not JAVA_CMD:
        print("Warning: Java not found. PDF export will use browser print.")
    if not FOP_JAR:
        print("Warning: Apache FOP not found. PDF export will use browser print.")
        print(
            "\tTo enable native PDF: run 'ant provide-fop' or download FOP to lib/fop/"
        )

# XML namespaces for document type detection
NAMESPACES = {
    "ubl_invoice": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "ubl_creditnote": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cii": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
}


def detect_document_type(xml_content):
    """Detect the type of XRechnung document"""
    try:
        root = etree.fromstring(xml_content)
        ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""

        if ns == NAMESPACES["ubl_invoice"]:
            return "ubl_invoice"
        elif ns == NAMESPACES["ubl_creditnote"]:
            return "ubl_creditnote"
        elif ns == NAMESPACES["cii"]:
            return "cii"
        return None
    except Exception:
        return None


def transform_xml(xml_content, lang="de"):
    """Transform XML to HTML using XSLT"""
    doc_type = detect_document_type(xml_content)
    if not doc_type:
        raise ValueError(
            "Unknown XML format. "
            "Supported: UBL Invoice, UBL CreditNote, CII/UNCEFACT"
        )

    xsl_mapping = {
        "ubl_invoice": "ubl-invoice-xr.xsl",
        "ubl_creditnote": "ubl-creditnote-xr.xsl",
        "cii": "cii-xr.xsl",
    }

    first_xsl = XSL_DIR / xsl_mapping[doc_type]
    html_xsl = XSL_DIR / "xrechnung-html.xsl"

    if not first_xsl.exists():
        raise FileNotFoundError(f"XSLT not found: {first_xsl}")
    if not html_xsl.exists():
        raise FileNotFoundError(f"XSLT not found: {html_xsl}")

    with PySaxonProcessor(license=False) as proc:
        xslt_proc = proc.new_xslt30_processor()
        xslt_proc.set_cwd(str(XSL_DIR))

        # First transformation: XML -> XR intermediate format
        executable1 = xslt_proc.compile_stylesheet(stylesheet_file=str(first_xsl))

        # Write XML to temp file for transformation
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".xml", delete=False) as f:
            f.write(xml_content)
            temp_xml = f.name

        try:
            xr_result = executable1.transform_to_string(source_file=temp_xml)
        finally:
            os.unlink(temp_xml)

        if not xr_result:
            raise RuntimeError("First XSLT transformation failed")

        # Second transformation: XR -> HTML
        executable2 = xslt_proc.compile_stylesheet(stylesheet_file=str(html_xsl))
        executable2.set_parameter("lang", proc.make_string_value(lang))

        html_result = executable2.transform_to_string(
            xdm_node=proc.parse_xml(xml_text=xr_result)
        )

        if not html_result:
            raise RuntimeError("Second XSLT transformation failed")

        return html_result


@app.route("/")
def index():
    return render_template("index.html", has_fop=HAS_FOP)


@app.route("/transform", methods=["POST"])
def transform():
    """Transform uploaded XML file"""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    lang = request.form.get("lang", "de")

    try:
        xml_content = file.read()
        html = transform_xml(xml_content, lang)
        return jsonify({"html": html, "filename": file.filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/export-pdf", methods=["POST"])
def export_pdf():
    """Export to PDF using xr-pdf.xsl and Apache FOP"""
    if not HAS_FOP:
        return jsonify({"error": "Apache FOP not installed"}), 500

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    lang = request.form.get("lang", "de")

    try:
        xml_content = file.read()
        doc_type = detect_document_type(xml_content)
        if not doc_type:
            raise ValueError("Unknown XML format")

        xsl_mapping = {
            "ubl_invoice": "ubl-invoice-xr.xsl",
            "ubl_creditnote": "ubl-creditnote-xr.xsl",
            "cii": "cii-xr.xsl",
        }

        first_xsl = XSL_DIR / xsl_mapping[doc_type]
        pdf_xsl = XSL_DIR / "xr-pdf.xsl"

        with PySaxonProcessor(license=False) as proc:
            xslt_proc = proc.new_xslt30_processor()
            xslt_proc.set_cwd(str(XSL_DIR))

            # First transformation: XML -> XR intermediate format
            executable1 = xslt_proc.compile_stylesheet(stylesheet_file=str(first_xsl))

            # Write XML to temp file for transformation
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".xml", delete=False
            ) as f:
                f.write(xml_content)
                temp_xml = f.name

            try:
                xr_result = executable1.transform_to_string(source_file=temp_xml)
            finally:
                os.unlink(temp_xml)

            if not xr_result:
                raise RuntimeError("First XSLT transformation failed")

            # Second transformation: XR -> XSL-FO
            executable2 = xslt_proc.compile_stylesheet(stylesheet_file=str(pdf_xsl))
            executable2.set_parameter("lang", proc.make_string_value(lang))
            executable2.set_parameter("foengine", proc.make_string_value("fop"))

            fo_result = executable2.transform_to_string(
                xdm_node=proc.parse_xml(xml_text=xr_result)
            )

            if not fo_result:
                raise RuntimeError("XSL-FO transformation failed")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".fo", delete=False, encoding="utf-8"
        ) as f:
            f.write(fo_result)
            temp_fo = f.name

        temp_pdf = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".pdf", delete=False
        ).name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xconf", delete=False, encoding="utf-8"
        ) as f:
            f.write(generate_fop_config())
            temp_fop_config = f.name

        try:
            fop_jars = list(FOP_HOME.glob("*.jar"))
            classpath = os.pathsep.join(str(j) for j in fop_jars)

            # Run FOP
            fop_cmd = [
                JAVA_CMD,
                "-cp",
                classpath,
                "org.apache.fop.cli.Main",
                "-c",
                temp_fop_config,
                "-fo",
                temp_fo,
                "-pdf",
                temp_pdf,
            ]

            result = subprocess.run(fop_cmd, capture_output=True, text=True)

            if os.path.exists(temp_pdf) and os.path.getsize(temp_pdf) > 0:
                with open(temp_pdf, "rb") as f:
                    pdf_content = f.read()

                filename = (
                    file.filename.replace(".xml", ".pdf")
                    if file.filename
                    else "xrechnung.pdf"
                )

                return Response(
                    pdf_content,
                    mimetype="application/pdf",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    },
                )
            else:
                error_msg = result.stderr or result.stdout or "FOP execution failed"
                raise RuntimeError(f"FOP error: {error_msg}")

        finally:
            if os.path.exists(temp_fo):
                os.unlink(temp_fo)
            if os.path.exists(temp_pdf):
                os.unlink(temp_pdf)
            if os.path.exists(temp_fop_config):
                os.unlink(temp_fop_config)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="XRechnung Viewer")
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host to bind to (default: localhost, use 0.0.0.0 for network access)",
    )
    parser.add_argument(
        "--port", type=int, default=4242, help="Port to listen on (default: 4242)"
    )
    parser.add_argument(
        "--dev", action="store_true", help="Run in development mode (Flask dev server)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("XRechnung Viewer")
    print("=" * 60)
    print()
    print(f"Starting server at: http://{args.host}:{args.port}")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)

    if args.dev:
        app.run(host=args.host, port=args.port, debug=False)
    else:
        from waitress import serve

        print("Running with Waitress (production server)")
        serve(app, host=args.host, port=args.port)
