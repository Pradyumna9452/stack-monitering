<?php
/*
** Copyright (C) 2021-2024 initMAX s.r.o.
**
** This program is free software: you can redistribute it and/or modify it under the terms of
** the GNU Affero General Public License as published by the Free Software Foundation, version 3.
**
** This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
** without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
** See the GNU Affero General Public License for more details.
**
** You should have received a copy of the GNU Affero General Public License along with this program.
** If not, see <https://www.gnu.org/licenses/>.
**/


namespace Modules\uxMAX\Services;

class DatabaseFont {

    protected string $png_thumbnail;
    protected int $idat_pos;

    const EXTENSION_CONTENT_TYPES = [
        'woff' => 'font/woff',
        'woff2' => 'font/woff2',
        'ttf' => 'font/ttf',
        'otf' => 'font/otf'
    ];

    const EXTENSION_FORMAT = [
        'woff' => 'woff',
        'woff2' => 'woff2',
        'ttf' => 'truetype',
        'otf' => 'opentype',
        'eot' => 'embedded-opentype'
    ];

    // Format string for naming PNG font files in the database.
    const PNG_NAME_FORMAT = 'uxMAXfont-%d.png';
    // Pattern to search for existing PNG font files in the database.
    const PNG_NAME_SEARCH = 'uxMAXfont-';

    /**
     * Load a PNG thumbnail file to be used as a template for embedding font data.
     *
     * @param string $png_src  Path to the PNG thumbnail file.
     */
    public function loadThumbnail(string $png_src): bool {
        if (!file_exists($png_src)) {
            error(_s('Thumbnail file does not exist: %1$s', $png_src));

            return false;
        }

        $png = file_get_contents($png_src);
        $pos = strpos($png, 'IDAT');

        if ($pos === false) {
            error(_s('Invalid thumbnail file: %1$s', $png_src));

            return false;
        }

        $this->png_thumbnail = $png;
        $this->idat_pos = $pos;

        return true;
    }

    /**
     * Create a PNG with embeded font data.
     *
     * @param string $font_data Base64 encoded font data.
     *
     * @return string The modified PNG data with embedded font.
     */
    public function createPngFont(string $font_data): string {
        $png = $this->png_thumbnail;
        $font_data_base64 = base64_encode($font_data);
        $chunk = 'uxMAX' . "\0" . $font_data_base64;
        $length = pack('N', strlen($chunk));
        $type = 'tEXt';
        $chunk = $length . $type . $chunk . pack('N', crc32($type . $chunk));
        // 4 bytes before IDAT (chunk length)
        $pos = $this->idat_pos - 4;

        return substr($png, 0, $pos) . $chunk . substr($png, $pos);
    }

    /**
     * Embed multiple data blocks into PNG.
     *
     * @param array $blocks  Array of data blocks to embed.
     *
     * @return string The modified PNG data with embedded blocks.
     */
    public function embedDataBlocksInPng(array $blocks): string {
        $png = $this->png_thumbnail;
        // 4 bytes before IDAT (chunk length)
        $pos = $this->idat_pos - 4;

        foreach (array_values($blocks) as $i => $data) {
            $chunk = "uxMAX-{$i}\0" . $data;
            $length = pack('N', strlen($chunk));
            $type = 'tEXt';
            $chunk = $length . $type . $chunk . pack('N', crc32($type . $chunk));
            $png = substr($png, 0, $pos) . $chunk . substr($png, $pos);
            $pos += strlen($chunk);
        }

        return $png;
    }

    /**
     * Extract a specific data block from PNG.
     *
     * @param string $png    Raw, non base 64 encoded, PNG data.
     * @param int    $index  Block index to extract.
     *
     * @return string|null The extracted data block or null if not found.
     */
    function getDataBlockFromPng($png, $index) {
        $offset = 8;
        $chunk_prefix = "uxMAX-$index";

        while ($offset < strlen($png)) {
            $length = unpack('N', substr($png, $offset, 4))[1];

            if (substr($png, $offset + 4, 4) === 'tEXt') {
                $chunk = substr($png, $offset + 8, $length);

                if (strpos($chunk, $chunk_prefix . "\0") === 0) {
                    return substr($chunk, strlen($chunk_prefix) + 1);
                }
            }

            // chunk header + data + CRC
            $offset += 8 + $length + 4;
        }

        return null;
    }
}