/**
 * Zabbix Media Type Script for GLPI Integration
 * 
 * This JavaScript runs inside Zabbix's embedded JavaScript engine.
 * It sends webhook requests to the GLPI Integration service for:
 * - Problem events (create tickets)
 * - Recovery events (close tickets)
 * - Update events (add followups)
 * 
 * INSTALLATION:
 * 1. Go to Administration > Media Types
 * 2. Create new Media Type of type "Webhook"
 * 3. Paste this script in the Script field
 * 4. Configure parameters (see below)
 * 5. Create a user "GLPI_Robot" and assign this media type
 * 6. Create Actions that send to GLPI_Robot
 * 
 * PARAMETERS (configure in Media Type):
 * - webhook_url: URL of the webhook server (e.g., http://glpi-webhook:5002/webhook)
 * - event_id: {EVENT.ID}
 * - event_name: {EVENT.NAME}
 * - event_severity: {EVENT.SEVERITY}
 * - event_status: {EVENT.STATUS}
 * - event_value: {EVENT.VALUE}
 * - event_update_status: {EVENT.UPDATE.STATUS}
 * - event_recovery_value: {EVENT.RECOVERY.VALUE}
 * - event_recovery_date: {EVENT.RECOVERY.DATE}
 * - event_recovery_time: {EVENT.RECOVERY.TIME}
 * - event_date: {EVENT.DATE}
 * - event_time: {EVENT.TIME}
 * - event_duration: {EVENT.DURATION}
 * - event_tags: {EVENT.TAGS}
 * - event_ack_status: {EVENT.ACK.STATUS}
 * - trigger_id: {TRIGGER.ID}
 * - trigger_name: {TRIGGER.NAME}
 * - trigger_description: {TRIGGER.DESCRIPTION}
 * - trigger_status: {TRIGGER.STATUS}
 * - trigger_severity: {TRIGGER.SEVERITY}
 * - host_name: {HOST.NAME}
 * - host_id: {HOST.ID}
 * - host_ip: {HOST.IP}
 * - host_dns: {HOST.DNS}
 * - host_conn: {HOST.CONN}
 * - item_name: {ITEM.NAME}
 * - item_value: {ITEM.VALUE}
 * - alert_subject: {ALERT.SUBJECT}
 * - alert_message: {ALERT.MESSAGE}
 * - ack_message: {ACK.MESSAGE}
 * - ack_user: {USER.FULLNAME}
 */

// Main script entry point
try {
    // Parse input parameters
    var params = JSON.parse(value);
    
    // Validate required parameters
    if (!params.webhook_url) {
        throw 'webhook_url parameter is required';
    }
    
    // Determine the action type based on event values
    var action = 'problem';
    var eventValue = parseInt(params.event_value) || 0;
    var recoveryValue = parseInt(params.event_recovery_value) || 0;
    var updateStatus = parseInt(params.event_update_status) || 0;
    
    // Event value: 1 = PROBLEM, 0 = OK
    // Recovery value: 1 if this is a recovery notification
    // Update status: 1 if this is an update (acknowledgment, etc.)
    
    if (recoveryValue === 1 || eventValue === 0) {
        action = 'recovery';
    } else if (updateStatus === 1) {
        action = 'update';
    } else if (eventValue === 1) {
        action = 'problem';
    }
    
    // Build the payload for the webhook
    var payload = {
        // Action type
        action: action,
        
        // Event information
        event_id: params.event_id || '',
        event_name: params.event_name || params.trigger_name || '',
        event_time: (params.event_date || '') + ' ' + (params.event_time || ''),
        
        // Status information
        status: eventValue === 1 ? 'PROBLEM' : 'OK',
        severity: params.event_severity || params.trigger_severity || '0',
        
        // Host information
        host: params.host_name || '',
        host_id: params.host_id || '',
        ip_address: params.host_ip || params.host_conn || '',
        
        // Trigger information
        trigger: params.trigger_name || params.event_name || '',
        trigger_id: params.trigger_id || '',
        trigger_description: params.trigger_description || '',
        description: params.trigger_description || params.alert_message || '',
        
        // Item information
        item_name: params.item_name || '',
        item_value: params.item_value || '',
        
        // Operational data
        operational_data: params.item_value || '',
        
        // Tags
        tags: params.event_tags || '',
        
        // Recovery information (for recovery actions)
        recovery_time: (params.event_recovery_date || '') + ' ' + (params.event_recovery_time || ''),
        recovery_event_id: params.event_id || '',
        duration: params.event_duration || '',
        
        // Update/Acknowledgment information
        message: params.ack_message || params.alert_message || '',
        ack_message: params.ack_message || '',
        user: params.ack_user || '',
        ack_user: params.ack_user || '',
        ack_status: params.event_ack_status || '0'
    };
    
    // Log the action being taken
    Zabbix.log(4, '[GLPI Integration] Action: ' + action + ', Event ID: ' + payload.event_id + ', Host: ' + payload.host);
    
    // Create HTTP request
    var request = new HttpRequest();
    request.addHeader('Content-Type: application/json');
    
    // Set timeout (10 seconds)
    // Note: HttpRequest timeout is in seconds in Zabbix
    
    // Send the request
    var url = params.webhook_url;
    var response = request.post(url, JSON.stringify(payload));
    
    // Parse response
    var responseCode = request.getStatus();
    
    Zabbix.log(4, '[GLPI Integration] Response code: ' + responseCode);
    Zabbix.log(4, '[GLPI Integration] Response body: ' + response);
    
    // Check response
    if (responseCode < 200 || responseCode >= 300) {
        throw 'HTTP request failed with code ' + responseCode + ': ' + response;
    }
    
    // Parse JSON response
    var result;
    try {
        result = JSON.parse(response);
    } catch (e) {
        // Response might not be JSON, that's okay
        result = { status: 'ok', raw_response: response };
    }
    
    // Check for error in response
    if (result.status === 'error') {
        throw 'GLPI Integration error: ' + (result.message || 'Unknown error');
    }
    
    // Return success with ticket ID if available
    var returnMessage = 'OK';
    if (result.ticket_id) {
        returnMessage = 'Ticket #' + result.ticket_id;
        if (result.status === 'created') {
            returnMessage += ' created';
        } else if (result.status === 'closed') {
            returnMessage += ' closed';
        } else if (result.status === 'updated') {
            returnMessage += ' updated';
        }
    }
    
    return JSON.stringify({ message: returnMessage, ticket_id: result.ticket_id || '' });
    
} catch (error) {
    Zabbix.log(3, '[GLPI Integration] Error: ' + error);
    throw 'GLPI Integration failed: ' + JSON.stringify({ error: error.toString() });
}
