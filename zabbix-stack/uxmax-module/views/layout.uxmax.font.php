<?php

if (array_key_exists('font', $data)) {
    header('Content-type: '.$data['content_type'], true);
    header('Content-Disposition: attachment; filename="'.rawurlencode($data['file_name']).'"');

    echo $data['font'];
}
