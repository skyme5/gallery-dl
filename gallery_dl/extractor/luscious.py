# -*- coding: utf-8 -*-

# Copyright 2016-2019 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://members.luscious.net/"""

from .common import Extractor, Message
from .. import text, exception


class LusciousExtractor(Extractor):
    """Base class for luscious extractors"""
    category = "luscious"
    cookiedomain = ".luscious.net"
    root = "https://members.luscious.net"

    def _graphql(self, op, variables, query):
        data = {
            "id": 1,
            "operationName": op,
            "query": query,
            "variables": variables,
        }
        response = self.request(
            "{}/graphql/nobatch/?operationName={}".format(self.root, op),
            method="POST", json=data, fatal=False,
        )

        if response.status_code >= 400:
            self.log.error("GraphQL query failed ('%s %s')",
                           response.status_code, response.reason)
            self.log.debug("Server response: %s", response.text)
            raise exception.StopExtraction()

        return response.json()["data"]


class LusciousAlbumExtractor(LusciousExtractor):
    """Extractor for image albums from luscious.net"""
    subcategory = "album"
    filename_fmt = "{category}_{album[id]}_{num:>03}.{extension}"
    directory_fmt = ("{category}", "{album[id]} {album[title]}")
    archive_fmt = "{album[id]}_{id}"
    pattern = (r"(?:https?://)?(?:www\.|members\.)?luscious\.net"
               r"/(?:albums|pictures/c/[^/?&#]+/album)/[^/?&#]+_(\d+)")
    test = (
        ("https://luscious.net/albums/okinami-no-koigokoro_277031/", {
            "url": "7e4984a271a1072ac6483e4228a045895aff86f3",
            #  "keyword": "07c0b915f2ab1cc3bbf28b76e7950fccee1213f3",
            "content": "b3a747a6464509440bd0ff6d1267e6959f8d6ff3",
        }),
        ("https://luscious.net/albums/virgin-killer-sweater_282582/", {
            "url": "21cc68a7548f4d71dfd67d8caf96349dde7e791c",
            #  "keyword": "e1202078b504adeccd521aa932f456a5a85479a0",
        }),
        ("https://luscious.net/albums/not-found_277035/", {
            "exception": exception.NotFoundError,
        }),
        ("https://members.luscious.net/albums/login-required_323871/", {
            "count": 78,
        }),
        ("https://www.luscious.net/albums/okinami_277031/"),
        ("https://members.luscious.net/albums/okinami_277031/"),
        ("https://luscious.net/pictures/c/video_game_manga/album"
         "/okinami-no-koigokoro_277031/sorted/position/id/16528978/@_1"),
    )

    def __init__(self, match):
        LusciousExtractor.__init__(self, match)
        self.album_id = match.group(1)

    def items(self):
        album = self.metadata()
        yield Message.Version, 1
        yield Message.Directory, {"album": album}
        for num, image in enumerate(self.images(), 1):
            image["num"] = num
            image["album"] = album
            url = image["url_to_video"] or image["url_to_original"]
            yield Message.Url, url, text.nameext_from_url(url, image)

    def metadata(self):
        variables = {
            "id": self.album_id,
        }
        query = (
            "query AlbumGet($id: ID!) { album { get(id: $id) { ... on Album { "
            "...AlbumStandard } ... on MutationError { errors { code message }"
            " } } } } fragment AlbumStandard on Album { __typename id title la"
            "bels description created modified like_status number_of_favorites"
            " rating status marked_for_deletion marked_for_processing number_o"
            "f_pictures number_of_animated_pictures slug is_manga url download"
            "_url permissions cover { width height size url } created_by { id "
            "name display_name user_title name display_name avatar { url size "
            "} url } content { id title url } language { id title url } tags {"
            " id category slug text url count } genres { id title slug url } a"
            "udiences { id title url url } last_viewed_picture { id position u"
            "rl } }"
        )

        data = self._graphql("AlbumGet", variables, query)["album"]["get"]
        if "errors" in data:
            raise exception.NotFoundError("album")
        return data

    def images(self):
        variables = {
            "input": {
                "filters": [{
                    "name" : "album_id",
                    "value": self.album_id,
                }],
                "display": "position",
                "page"   : 1,
            },
        }
        query = (
            "query AlbumListOwnPictures($input: PictureListInput!) { picture {"
            " list(input: $input) { info { ...FacetCollectionInfo } items { .."
            ".PictureStandardWithoutAlbum } } } } fragment FacetCollectionInfo"
            " on FacetCollectionInfo { page has_next_page has_previous_page to"
            "tal_items total_pages items_per_page url_complete url_filters_onl"
            "y } fragment PictureStandardWithoutAlbum on Picture { __typename "
            "id title created like_status number_of_comments number_of_favorit"
            "es status width height resolution aspect_ratio url_to_original ur"
            "l_to_video is_animated position tags { id category slug text url "
            "} permissions url thumbnails { width height size url } }"
        )

        while True:
            data = self._graphql("AlbumListOwnPictures", variables, query)
            yield from data["picture"]["list"]["items"]

            if not data["picture"]["list"]["info"]["has_next_page"]:
                return
            variables["input"]["page"] += 1


class LusciousSearchExtractor(LusciousExtractor):
    """Extractor for album searches on luscious.net"""
    subcategory = "search"
    pattern = (r"(?:https?://)?(?:www\.|members\.)?luscious\.net"
               r"/albums/list/?(?:\?([^#]+))?")
    test = (
        ("https://members.luscious.net/albums/list/"),
        ("https://members.luscious.net/albums/list/"
         "?display=date_newest&language_ids=%2B1&tagged=+full_color&page=1", {
             "pattern": LusciousAlbumExtractor.pattern,
             "range": "41-60",
             "count": 20,
         }),
    )

    def __init__(self, match):
        LusciousExtractor.__init__(self, match)
        self.query = match.group(1)

    def items(self):
        query = text.parse_query(self.query)
        display = query.pop("display", "date_newest")
        page = query.pop("page", None)

        variables = {
            "input": {
                "display": display,
                "filters": [{"name": n, "value": v} for n, v in query.items()],
                "page": text.parse_int(page, 1),
            },
        }
        query = (
            "query AlbumListWithPeek($input: AlbumListInput!) { album { list(i"
            "nput: $input) { info { ...FacetCollectionInfo } items { ...AlbumM"
            "inimal peek_thumbnails { width height size url } } } } } fragment"
            " FacetCollectionInfo on FacetCollectionInfo { page has_next_page "
            "has_previous_page total_items total_pages items_per_page url_comp"
            "lete url_filters_only } fragment AlbumMinimal on Album { __typena"
            "me id title labels description created modified number_of_favorit"
            "es number_of_pictures slug is_manga url download_url cover { widt"
            "h height size url } content { id title url } language { id title "
            "url } tags { id category slug text url count } genres { id title "
            "slug url } audiences { id title url } }"
        )

        yield Message.Version, 1
        while True:
            data = self._graphql("AlbumListWithPeek", variables, query)

            for album in data["album"]["list"]["items"]:
                album["url"] = self.root + album["url"]
                album["_extractor"] = LusciousAlbumExtractor
                yield Message.Queue, album["url"], album

            if not data["album"]["list"]["info"]["has_next_page"]:
                return
            variables["input"]["page"] += 1
