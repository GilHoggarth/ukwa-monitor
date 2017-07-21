import io
import os
import json
import logging
import datetime
from requests.utils import quote
import xml.dom.minidom
import requests
from pywb.warc.recordloader import ArcWarcRecordLoader
from pywb.utils.bufferedreaders import DecompressingBufferedReader

logger = logging.getLogger(__name__)

WEBHDFS_PREFIX = os.environ.get('WEBHDFS_PREFIX', 'http://localhost:50070/webhdfs/v1')
WEBHDFS_USER = os.environ.get('WEBHDFS_USER', 'hdfs')
CDX_SERVER = os.environ.get('CDX_SERVER','http://localhost:9090/fc')

WAYBACK_TS_FORMAT = '%Y%m%d%H%M%S'


def get_rendered_original(url, render_type='screenshot', target_date=datetime.datetime.today()):
    # Query URL
    qurl = "%s:%s" % (render_type, url)
    # Query CDX Server for the item
    #logger.info("Querying CDX for prefix...")
    warc_filename, warc_offset, compressedendoffset = lookup_in_cdx(qurl)

    # If not found, say so:
    if warc_filename is None:
        return None, None

    # Grab the payload from the WARC and return it.
    url = "%s%s?op=OPEN&user.name=%s&offset=%s" % (WEBHDFS_PREFIX, warc_filename, WEBHDFS_USER, warc_offset)
    if compressedendoffset:
        url = "%s&length=%s" % (url, compressedendoffset)
    #logger.info("Requesting copy from HDFS: %s " % url)
    r = requests.get(url, stream=True)
    #logger.info("Loading from: %s" % r.url)
    r.raw.decode_content = False
    rl = ArcWarcRecordLoader()
    #logger.info("Passing response to parser...")
    record = rl.parse_record_stream(DecompressingBufferedReader(stream=r.raw))
    #logger.info("RESULT:")
    #logger.info(record)

    #logger.info("Returning stream...")
    return record.stream, record.content_type


def lookup_in_cdx(qurl, target_date=datetime.datetime.today()):
    """
    Checks if a resource is in the CDX index, closest to a specific date:

    :return:
    """
    matches = list_from_cdx(qurl)
    if len(matches) == 0:
        return None, None, None

    # Go through looking for the closest match:
    matched_date = None
    matched_ts = None
    for ts in matches.keys():
        wb_date = datetime.datetime.strptime(ts, WAYBACK_TS_FORMAT)
        if matched_date is None or wb_date-target_date < matched_date-target_date:
            matched_date = wb_date
            matched_ts = ts

    return matches[matched_ts]


def list_from_cdx(qurl):
    """
    Checks if a resource is in the CDX index.

    :return: a list of matches by timestamp
    """
    query = "%s?q=type:urlquery+url:%s" % (CDX_SERVER, quote(qurl))
    r = requests.get(query)
    logger.debug("Availability response: %d" % r.status_code)
    result_set = {}
    # Is it known, with a matching timestamp?
    if r.status_code == 200:
        try:
            dom = xml.dom.minidom.parseString(r.text)
            for result in dom.getElementsByTagName('result'):
                warc_file = result.getElementsByTagName('file')[0].firstChild.nodeValue
                compressed_offset = result.getElementsByTagName('compressedoffset')[0].firstChild.nodeValue
                capture_date = result.getElementsByTagName('capturedate')[0].firstChild.nodeValue
                # Support compressed record length if present:
                compressed_end_offset_elem = result.getElementsByTagName('compressedendoffset')
                if len(compressed_end_offset_elem) > 0:
                    compressed_end_offset = compressed_end_offset_elem[0].firstChild.nodeValue
                else:
                    compressed_end_offset = None
                result_set[capture_date] = warc_file, compressed_offset, compressed_end_offset
        except Exception as e:
            logger.error("Lookup failed for %s!" % qurl)
            logger.exception(e)

    return result_set
