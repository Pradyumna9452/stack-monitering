'use strict';

class CWidgetSonicOverview extends CWidget {

    /**
     * Return extra data sent with each refresh request.
     * Nothing widget-specific needed here.
     */
    getUpdateRequestData() {
        return {
            ...super.getUpdateRequestData()
        };
    }

    /**
     * Called after the server response is rendered into the widget body.
     * Apply any post-render DOM tweaks here.
     */
    setContents(response) {
        super.setContents(response);

        // Highlight rows whose alarm count > 0 with a subtle background
        const rows = this._target.querySelectorAll('.sonic-table tbody tr');
        rows.forEach(row => {
            const alarmCell = row.querySelector('.sonic-alarms');
            if (alarmCell && parseInt(alarmCell.textContent, 10) > 0) {
                row.style.backgroundColor = 'rgba(252, 129, 129, 0.08)';
            }
        });
    }
}
