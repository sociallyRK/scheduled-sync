import os, re, json, traceback
from pathlib import Path
from datetime import datetime
from flask import Flask, request, render_template, redirect, session, url_for, flash, jsonify
from geotext import GeoText
import pycountry
from werkzeug.middleware.proxy_fix import ProxyFix
from oauth_gcal import begin_auth, finish_auth, require_gcal, build_service, health

try:
    from dateparser import parse as _parse_date
except Exception:
    from dateutil import parser as _du_parser
    _parse_date = _du_parser.parse

# (… full code continues …)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
