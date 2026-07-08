"""
Firebase Cloud Messaging (FCM) Service using HTTP v1 API.

Mirrors the Laravel FcmService — sends push notifications using Firebase service accounts
and handles dead token cleanup.
"""

import os
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class FcmService:
    def send_to_tokens(self, tokens, title, body, data=None):
        """
        Sends an FCM push notification to a list of device tokens.
        If a token is dead/unregistered, deletes it from AgentDeviceToken.
        """
        if data is None:
            data = {}

        project_id = getattr(settings, 'FCM_PROJECT_ID', '')
        service_account_path = getattr(settings, 'FCM_SERVICE_ACCOUNT_JSON', '')

        # Resolve path to absolute if configured
        if service_account_path and not os.path.isabs(service_account_path):
            service_account_path = os.path.join(settings.BASE_DIR, service_account_path)

        if not project_id or not service_account_path or not tokens:
            logger.warning('FCM skipped: missing project_id, service_account_json, or tokens.')
            return

        if not os.path.isfile(service_account_path):
            logger.warning(f'FCM service account JSON not found at path: {service_account_path}')
            return

        # Attempt to import google-auth components
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests
        except ImportError:
            logger.warning('FCM skipped: google-auth package is not installed.')
            return

        try:
            scopes = ['https://www.googleapis.com/auth/firebase.messaging']
            creds = service_account.Credentials.from_service_account_file(
                service_account_path, scopes=scopes
            )

            # Retrieve OAuth2 Access Token
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            access_token = creds.token

            if not access_token:
                logger.warning('FCM: could not obtain access token from service account.')
                return

            endpoint = f'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }

            from apps.admin_panel.views.broadcast import AgentDeviceToken
            for token in tokens:
                if not token or not token.strip():
                    continue

                payload = {
                    'message': {
                        'token': token,
                        'notification': {
                            'title': title,
                            'body': body,
                        },
                        'android': {
                            'priority': 'high',
                            'notification': {
                                'sound': 'default',
                            },
                        },
                        'webpush': {
                            'notification': {
                                'title': title,
                                'body': body,
                                'icon': '/pwa/pwa-192.png',
                                'badge': '/pwa/pwa-72.png',
                                'requireInteraction': True,
                                'vibrate': [200, 100, 200],
                            },
                            'headers': {
                                'Urgency': 'high',
                            },
                            'fcm_options': {
                                'link': '/agent/dashboard',
                            },
                        },
                        'apns': {
                            'headers': {
                                'apns-priority': '10',
                            },
                            'payload': {
                                'aps': {
                                    'alert': {
                                        'title': title,
                                        'body': body,
                                    },
                                    'sound': 'default',
                                },
                            },
                        },
                    }
                }

                if data:
                    string_data = {str(k): str(v) for k, v in data.items()}
                    payload['message']['data'] = string_data

                try:
                    response = requests.post(endpoint, json=payload, headers=headers, timeout=20)

                    if not (200 <= response.status_code < 300):
                        try:
                            error_body = response.json()
                        except ValueError:
                            error_body = {}

                        error_details = error_body.get('error', {}).get('details', [])
                        error_code = None
                        if error_details and isinstance(error_details, list):
                            error_code = error_details[0].get('errorCode')

                        logger.warning(
                            f"FCM send failed for token {token[:20]}...: Status {response.status_code}, Body: {response.text}"
                        )

                        # Delete stale/dead token if status is 404 or errorCode indicates unregistered
                        if response.status_code == 404 or error_code in ('UNREGISTERED', 'INVALID_ARGUMENT'):
                            AgentDeviceToken.objects.filter(token=token).delete()
                            logger.info(f"Deleted stale FCM token from database: {token[:20]}...")

                    else:
                        logger.info(f"FCM push sent successfully to token {token[:20]}...")

                except requests.RequestException as e:
                    logger.error(f"FCM send request failed for token {token[:20]}...: {e}")

        except Exception as e:
            logger.exception(f"FCM general exception: {e}")
