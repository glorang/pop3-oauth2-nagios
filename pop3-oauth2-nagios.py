#!/usr/bin/env python3
#
# Nagios plugin to check message count and age in an Office 365 POP3 mailbox using OAuth2 authentication
#
# 2022-09-29 - glorang
#

import os, sys, configparser, argparse, requests, base64, re
import email.utils
from popliboauth import POP3_SSL
from datetime import datetime, timedelta

POP3_DEBUGLEVEL=0
NAGIOS_OK=0
NAGIOS_WARNING=1
NAGIOS_CRITICAL=2
NAGIOS_UNKNOWN=3

# Get arguments
parser = argparse.ArgumentParser(description='Nagios plugin to check message count and age in an Office 365 POP3 mailbox using OAuth2 authentication')
parser.add_argument('-u', '--username', nargs='?', required=True, type=str, help='Username of mailbox to check')
parser.add_argument('-w', '--warning', nargs='?', required=True, type=int, help='Time (in hours) for this check to go in WARNING state')
parser.add_argument('-c', '--critical', nargs='?', required=True, type=int, help='Time (in hours) for this check to go in CRITICAL state')
args = parser.parse_args()

# Import config
cwd = os.path.dirname(os.path.realpath(__file__))
configFile = "%s/pop3-oauth2-nagios.cfg" % cwd
if not os.path.isfile(configFile):
	print("UNKNOWN - Config file %s does not exist" % configFile)
	sys.exit(NAGIOS_UNKNOWN)

config = configparser.ConfigParser()
config.read(configFile)

# Config validation
if not config.has_section("general"):
	print("UNKNOWN - Config file has no section general")
	sys.exit(NAGIOS_UNKNOWN)

for option in ["server", "tenant", "scope"]:
	if not config.has_option("general", option):
		print("UNKNOWN - Required option '%s' in section general missing" % option)
		sys.exit(NAGIOS_UNKNOWN)

# Check if config exist for requested username (and is valid)
if not config.has_section(args.username):
	print("UNKNOWN - Config file has no config defined for mailbox '%s'" % args.username)
	sys.exit(NAGIOS_UNKNOWN)

for option in ["clientid", "secret"]:
	if not config.has_option(args.username, option):
		print("UNKNOWN - Required option '%s' in section '%s' missing" % (option, args.username))
		sys.exit(NAGIOS_UNKNOWN)

# Parse token cache
tokenFile = "%s/pop3-oauth2-nagios.tokens" % cwd
token=None
expiry=None
if os.path.isfile(tokenFile):
	tokenCache = configparser.ConfigParser()
	tokenCache.read(tokenFile)

	try:
		token = tokenCache.get(args.username, "token")
		expiry = datetime.fromisoformat(tokenCache.get(args.username, "expiry"))
	except Exception as e:
		# we'll get a new one if cache failed
		pass

# Get new token if token is expired or no token is present in cache 
if not token or datetime.now() > expiry:

	# Prepare token data
	tokenServer = "https://login.microsoftonline.com/%s/oauth2/v2.0/token" % config.get("general", "tenant")
	postData = {
	  "grant_type": "client_credentials",
	  "client_id": config.get(args.username, "clientid"),
	  "scope": config.get("general", "scope"),
	  "client_secret": config.get(args.username, "secret"),
	}

	# Get new token
	postRequest = requests.post(tokenServer, data=postData)

	# Check reponse
	if postRequest.status_code != 200:
		print("UNKNOWN - No token found in cache and could not get a new one")
		sys.exit(NAGIOS_UNKNOWN)
	
	# Get response body
	response = postRequest.json()

	# Check if reponse has required values
	if not 'expires_in' in response or not 'access_token' in response:
		print("UNKNOWN - Fields 'expires_in' or 'access_token' are missing in token response")
		sys.exit(NAGIOS_UNKNOWN)

	# Store values in cache
	try:
		token = response["access_token"]
		expiry = (datetime.now() + timedelta(seconds=response['expires_in'])).isoformat()
		tokenCache = configparser.ConfigParser()
		tokenCache.read(tokenFile)
		if not tokenCache.has_section(args.username):
			tokenCache.add_section(args.username)
		tokenCache.set(args.username, "token", token)
		tokenCache.set(args.username, "expiry", expiry)

		with open(tokenFile, 'w') as f:
		    tokenCache.write(f)

	except Exception as e:
		print("UNKNOWN - Could not update cache: %s" % e)
		sys.exit(NAGIOS_UNKNOWN)

# At this point we must have a valid token
if not token:
	print("CRITICAL - Could not get token for mailbox '%s'" % args.username)
	sys.exit(NAGIOS_CRITICAL)

# Setup base64 authentication string (https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth)
authentication_string = "user=" + args.username + '\x01' + "auth=Bearer " + token + '\x01' + '\x01'
authentication_string_encoded = base64.b64encode(authentication_string.encode('utf-8'))

# Check for messages on the server and get date of oldest message
count = -1
delta = 0
try:
	pop3 = POP3_SSL(config.get("general", "server"))
	pop3.set_debuglevel(POP3_DEBUGLEVEL)
	pop3.oauth(authentication_string_encoded.decode('utf-8'))

	# Get message count
	count = pop3.stat()[0]

	# Get date from oldest message on server
	if count > 0:
		first_message = pop3.top(1, 1)[1]
		for line in first_message:
			line_decoded = line.decode('utf-8')
			date_regex = re.compile("^Date:\s+(.+)$")
			if date_regex.match(line_decoded):
				date_line = date_regex.match(line_decoded).group(1)
				date = email.utils.parsedate_to_datetime(date_line).replace(tzinfo=None)
				delta = (datetime.now() - date).total_seconds() / 60 / 60
	# Close connection
	pop3.quit()

except Exception as e:

	# Make sure connection is closed if something failed
	try:
		pop3.quit()
	except:
		pass

	print("CRITICAL - Could not check for messages on the server: %s" % e)
	sys.exit(NAGIOS_CRITICAL)

# Print out result
message = ""
exitcode = 0

if count < 0:
	message = "CRITICAL - Could not check for messages on the server"
	exitcode = NAGIOS_CRITCAL
elif count == 0:
	message = "OK - No email messages present"
	exitcode = NAGIOS_OK
elif count > 0 and delta >= args.critical:
	message = "CRITICAL - Oldest message (on %s count total) for %s is %d hour(s) old" % (count, args.username, delta)
	exitcode = NAGIOS_CRITICAL
elif count > 0 and delta >= args.warning:
	message = "WARNING - Oldest message (on %s count total) for %s is %d hour(s) old" % (count, args.username, delta)
	exitcode = NAGIOS_WARNING
elif count > 0:
	message = "OK - Oldest message (on %s count total) for %s is %d hour(s) old" % (count, args.username, delta)
	exitcode = NAGIOS_OK

# Add performance data
message += " |age=%d;%d;%d;;" % (delta, args.warning, args.critical)

print(message)
sys.exit(exitcode)
