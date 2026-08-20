<?php

namespace Modules\uxMAX\Actions;

use API, CController, CControllerResponseData;
use Modules\uxMAX\Module;
use Modules\uxMAX\Services\DatabaseFont;

class Font extends CController {

    public Module $module;

    protected function init() {
        $this->disableCsrfValidation();
    }

    public function checkInput() {
        $fields = [
            'i' =>      'int32|required',
            'png' =>    'string|required',
            'format' => 'string|required|in woff,woff2,ttf,otf,eot'
        ];

        $ret = $this->validateInput($fields);

        if (!$ret) {
            $this->setResponse(new CControllerResponseData([
                'error' => _('Invalid input')
            ]));
        }

        return $ret;
    }

    public function checkPermissions() {
        return true;
    }

    public function doAction() {
        $png = API::Image()->get([
            'output' => [],
            'select_image' => true,
            'filter' => ['name' => $this->getInput('png')]
        ])[0];
        $database_font = new DatabaseFont;
        $format = $this->getInput('format');
        $content_type = DatabaseFont::EXTENSION_CONTENT_TYPES[$format] ?? 'application/octet-stream';
        $font = $database_font->getDataBlockFromPng(base64_decode($png['image']), $this->getInput('i'));

        $this->setResponse((new CControllerResponseData([
            'font' => $font,
            'file_name' => $this->getInput('png').'.'.$format,
            'content_type' => $content_type
        ])));
    }
}
