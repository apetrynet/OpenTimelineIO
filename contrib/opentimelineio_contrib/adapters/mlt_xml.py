#
# Copyright Contributors to the OpenTimelineIO project
#
# Licensed under the Apache License, Version 2.0 (the "Apache License")
# with the following modification; you may not use this file except in
# compliance with the Apache License and the following modification to it:
# Section 6. Trademarks. is deleted and replaced with:
#
# 6. Trademarks. This License does not grant permission to use the trade
#    names, trademarks, service marks, or product names of the Licensor
#    and its affiliates, except as required to comply with Section 4(c) of
#    the License and to reproduce the content of the NOTICE file.
#
# You may obtain a copy of the Apache License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the Apache License with the above modification is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the Apache License for the specific
# language governing permissions and limitations under the Apache License.
#

"""
The MLT adapter currently only supports writing simplified mlt xml files
geared towards use with the "melt" command line video editor.

Example: `melt my_converted_otio_file.mlt [OPTIONS]`

The motivation for writing this adapter was playback of timeline's or
rendering of mini cut's for instance and not parsing project files for
applications based on MLT such as kdenlive, Shotcut etc.
There already exists an adapter for kdenlive files in OTIO.

Therefore, reading of mlt files is not supported at the moment.
This is also partly due to the flexible nature of the MLT format making it a
bit hard to write a solid parser based on etree.

If someone wants to implement parsing/reading of mlt files feel free to do so.
You might want to use the python-mlt bindings available for a more robust
parser, but please note that adds a third-party dependency to the adapter.

For more info on the MLT visit the website: https://www.mltframework.org/
"""

import opentimelineio as otio
from copy import deepcopy
from fractions import Fraction
from xml.dom import minidom
from xml.etree import ElementTree as et

# MLT root tag
root = et.Element('mlt')

# Store media references or clips as producers
producers = {'audio': {}, 'video': {}}

# Store playlists so they appear in order
playlists = []

# Store transitions for indexing
transitions = []


def create_property_element(name, text=None, attrib=None):
    property_e = et.Element('property', name=name)
    if text is not None:
        property_e.text = str(text)

    if attrib:
        property_e.attrib.update(attrib)

    return property_e


def create_solid(color, length):
    color_e = et.Element(
        'producer',
        title='color',
        id='solid_{c}'.format(c=color),
        attrib={'in': '0', 'out': str(length - 1)}
    )

    color_e.append(create_property_element('length', length))
    color_e.append(create_property_element('eof', 'pause'))
    color_e.append(create_property_element('resource', color))
    color_e.append(create_property_element('mlt_service', 'color'))

    return color_e


def get_producer(otio_item, video_track=True):
    target_url = None
    producer_e = None
    is_sequence = False

    if isinstance(otio_item, (otio.schema.Gap, otio.schema.Transition)):
        # Create a solid producer
        producer_e = create_solid(
            'black',
            otio_item.duration().value
        )

        id_ = producer_e.attrib['id']

    else:
        id_ = otio_item.name

    if hasattr(otio_item, 'media_reference') and otio_item.media_reference:
        id_ = otio_item.media_reference.name or otio_item.name

        if hasattr(otio_item.media_reference, 'target_url'):
            target_url = otio_item.media_reference.target_url

        elif hasattr(otio_item.media_reference, 'abstract_target_url'):
            is_sequence = True
            target_url = otio_item.media_reference.abstract_target_url(
                '%0{}d'.format(
                    otio_item.media_reference.frame_zero_padding
                )
            )
            target_url += '?begin={}'.format(
                otio_item.media_reference.start_frame
            )

    if producer_e is None:
        producer_e = et.Element(
            'producer',
            id=id_
        )

    sub_key = 'video'
    if not video_track:
        sub_key = 'audio'

    # We keep track of audio and video producers to avoid duplicates
    producer = producers[sub_key].setdefault(
        id_,
        producer_e
    )

    if not target_url:
        target_url = id_

    property_e = producer.find('./property/[@name="resource"]')
    if property_e is None or property_e.text == 'black':
        if property_e is None:
            resource = create_property_element(
                name='resource',
                text=target_url
            )
            producer.append(resource)

        if is_sequence:
            producer.append(
                create_property_element(name='mlt_service', text='pixbuf')
            )

        # store producer in order list for insertion later
        order = producers.setdefault('producer_order_', [])
        if producer not in order:
            order.append(producer)

    return producer


def create_transition(trans_tuple, name):
    # Expand parts of transition
    item_a, transition, item_b = trans_tuple

    dur = transition.duration().value - 1

    tractor_e = et.Element(
        'tractor',
        id=name,
        attrib={
            'in': '0',
            'out': str(dur)
        }
    )

    producer_a = get_producer(item_a)
    if isinstance(item_a, otio.schema.Gap):
        a_in = 0
        a_out = item_b.duration().value - 1

    else:
        a_in = item_a.trimmed_range().start_time.value
        a_out = a_in + item_a.trimmed_range().duration.value - 1

    track_a = et.Element(
        'track',
        producer=producer_a.attrib['id'],
        attrib={
            'in': str(a_in),
            'out': str(a_out)
        }
    )

    producer_b = get_producer(item_b)
    if isinstance(item_b, otio.schema.Gap):
        b_in = 0
        b_out = item_b.duration().value - 1

    else:
        b_in = item_b.trimmed_range().start_time.value
        b_out = b_in + item_b.trimmed_range().duration.value - 1

    track_b = et.Element(
        'track',
        producer=producer_b.attrib['id'],
        attrib={
            'in': str(b_in),
            'out': str(b_out)
        }
    )

    tractor_e.append(track_a)
    tractor_e.append(track_b)

    trans_e = et.Element(
        'transition',
        id='transition_{}'.format(name),
        out=str(dur)
    )
    trans_e.append(create_property_element('a_track', 0))
    trans_e.append(create_property_element('b_track', 1))
    trans_e.append(create_property_element('factory'))
    trans_e.append(create_property_element('mlt_service', 'luma'))

    tractor_e.append(trans_e)

    return tractor_e


def create_entry_element(producer, in_, out_):
    clip_e = et.Element(
        'entry',
        producer=producer.attrib['id'],
        attrib={
            'in': str(in_),
            'out': str(out_)
        }
    )

    return clip_e


def create_clip(item, producer):
    in_ = item.trimmed_range().start_time.value
    out_ = in_ + item.trimmed_range().duration.value - 1

    clip_e = create_entry_element(producer, in_, out_)

    return clip_e


def create_blank_element(item):
    blank_e = et.Element(
        'blank',
        length=str(item.source_range.duration.value)
    )

    return blank_e


def apply_timewarp(item, item_e, effect):
    """
    Apply a time warp effect on a copy of a producer

    :param item: source OTIO item in track
    :param item_e: element tag to apply effect to
    :param effect: OTIO effect object
    :return:
    """

    if item_e is None:
        return

    # Create a copy of the producer
    orig_producer_e = get_producer(item)
    producer_e = deepcopy(orig_producer_e)
    id_ = None

    if effect.effect_name == 'FreezeFrame':
        # Freeze frame will always use the first frame of the source_range as
        # OTIO doesn't really have  any other way of indicating which frame was
        # chosen to freeze

        id_ = '{}_freeze{}'.format(
            producer_e.attrib['id'],
            item.source_range.start_time.value
        )

        producer_e.attrib['id'] = id_
        producer_e.append(create_property_element('mlt_service', 'hold'))
        producer_e.append(create_property_element(
            'frame',
            str(item.source_range.start_time.value))
        )

    elif effect.effect_name == 'LinearTimeWarp':
        id_ = ':'.join(
            [str(effect.time_scalar), item_e.attrib.get('producer')]
        )
        producer_e.attrib['id'] = id_
        producer_e.append(create_property_element('mlt_service', 'timewarp'))
        resource_e = producer_e.find('./property/[@name="resource"]')
        resource_e.text = ':'.join([str(effect.time_scalar), resource_e.text])

    # Add the new copy to the producers list
    if id_ not in producers['video']:
        producers['video'][id_] = producer_e
        producers['producer_order_'].append(producer_e)

    # Swap the old producer with the new containing the effect
    item_e.attrib['producer'] = id_


def create_background_track(tracks, parent):
    length = tracks.duration().value
    bg_e = create_solid('black', length)

    # Add producer to list
    producer_e = producers['video'].setdefault(bg_e.attrib['id'], bg_e)

    # store producer in order list for insertion later
    producers.setdefault('producer_order_', []).append(producer_e)

    playlist_e = et.Element(
        'playlist',
        id='background'
    )
    playlists.append(playlist_e)

    playlist_e.append(create_entry_element(bg_e, 0, length - 1))

    parent.append(
        et.Element('track', producer=playlist_e.attrib['id'])
    )


def assemble_track(track, track_index, parent):
    playlist_e = et.Element(
        'playlist',
        id=track.name or 'playlist{}'.format(track_index)
    )
    playlists.append(playlist_e)

    # Transitions use track elements as children
    element_type = 'track'

    # Playlists use entry
    if parent.tag == 'playlist':
        element_type = 'entry'

    parent.append(
        et.Element(element_type, producer=playlist_e.attrib['id'])
    )

    # Used to check if we need to add audio elements or not
    is_audio_track = False
    if hasattr(track, 'kind'):
        is_audio_track = track.kind == 'Audio'

    # Iterate over items in track, expanding transitions
    expanded_track = otio.algorithms.track_with_expanded_transitions(track)
    for item in expanded_track:
        item_e = None

        if isinstance(item, otio.schema.Clip):
            producer_e = get_producer(item)

            if is_audio_track:
                # Skip adding duplicate audio source for matching video
                if producer_e.attrib['id'] in producers['video']:
                    continue

            item_e = create_clip(item, producer_e)
            playlist_e.append(item_e)

        elif isinstance(item, otio.schema.Gap):
            item_e = create_blank_element(item)
            playlist_e.append(item_e)

        elif isinstance(item, tuple):
            # Since we expanded transitions in the track the come as tuples
            # containing (ClipA_t, Transition, ClipB_t)

            transition_e = create_transition(
                item,
                'transition_tractor{}'.format(len(transitions))
            )
            transitions.append(transition_e)

            playlist_e.append(
                et.Element(
                    'entry',
                    producer=transition_e.attrib['id'],
                    attrib={
                        'in': transition_e.attrib['in'],
                        'out': transition_e.attrib['out']
                    }
                )
            )

            # Continue as transitions have no effects, see test below
            continue

        elif 'Stack' in item.schema_name():
            assemble_track(item, track_index, playlist_e)

        # Check for effects on item
        for effect in item.effects:
            # We only support certain time effects for now
            if isinstance(effect, otio.schema.TimeEffect):
                apply_timewarp(item, item_e, effect)


def assemble_timeline(tracks):
    # We gather tracks in tractors. This is the "main one"
    tractor_e = et.Element('tractor', id='tractor0')
    multitrack_e = et.SubElement(
        tractor_e,
        'multitrack',
        attrib={'id': 'multitrack0'}
    )

    root.append(tractor_e)

    # This is to make sure there is a solid background if tracks contain gaps
    create_background_track(tracks, multitrack_e)

    for track_index, track in enumerate(tracks):
        assemble_track(track, track_index, multitrack_e)


def rate_fraction_from_float(rate):
    """
    Given a frame rate float, creates a frame rate fraction conforming to known
    good rates where possible. This will do fuzzy matching of
    23.98 to 24000/1001, for instance.

    Thanks! @reinecke
    """

    # Whole numbers are easy
    if isinstance(rate, int) or rate.is_integer():
        return Fraction(rate)

    NTSC_RATES = (
        Fraction(24000, 1001),
        Fraction(30000, 1001),
        Fraction(60000, 1001),
    )

    for ntsc_rate in NTSC_RATES:
        # The tolerance of 0.004 comes from 24000/1001 - 23.98
        if abs(rate - ntsc_rate) < 0.004:
            return ntsc_rate

    return Fraction(rate)


def update_profile_element(profile_element, profile_data):
    if isinstance(profile_data, otio.opentime.RationalTime):
        fractional = rate_fraction_from_float(profile_data.rate)
        profile_data = dict(
            frame_rate_den=str(fractional.denominator),
            frame_rate_num=str(fractional.numerator)
        )

    elif not isinstance(profile_data, dict):
        raise ValueError(
            'Only pass global_start_time as RationalTime or'
            'a dict containing profile related key/value pairs.'
        )

    profile_element.attrib.update(profile_data)


def create_profile_element():
    profile_e = et.Element(
        'profile',
        decsription='automatic'
    )

    return profile_e


def write_to_string(input_otio, **profile_data):
    """

    :param input_otio: Timeline, Track, Stack or Clip
    :param profile_data: Properties passed to the profile tag describing
    the format, frame rate, colorspace and so on. If a passed Timeline has
    `global_start_time` set, the frame rate will be set automatically.
    Please check MLT website for more info on profiles.

    :return: MLT formatted XML
    :rtype: `str`
    """

    profile_e = create_profile_element()
    if profile_data:
        update_profile_element(profile_e, profile_data)

    if isinstance(input_otio, otio.schema.Timeline):
        tracks = input_otio.tracks
        if input_otio.global_start_time:
            update_profile_element(profile_e, input_otio.global_start_time)

    elif isinstance(input_otio, otio.schema.Track):
        stack = otio.schema.Stack()
        stack.children.append(input_otio)
        tracks = stack.children

    elif isinstance(input_otio, otio.schema.Stack):
        tracks = input_otio.children

    elif isinstance(input_otio, otio.schema.Clip):
        tmp_track = otio.schema.Track()
        tmp_track.append(input_otio)
        stack = otio.schema.Stack()
        stack.children.append(tmp_track)

        tracks = stack.children

    else:
        raise ValueError(
            "Passed OTIO item must be Timeline, Track, Stack or Clip. "
            "Not {}".format(type(input_otio))
        )

    # This is the part that iterates over the "tracks" and constructs elements
    assemble_timeline(tracks)

    # Below we add elements in an orderly fashion

    # Add producers to root
    for producer in producers['producer_order_']:
        root.insert(0, producer)

    # Add transition tractors
    for transition in transitions:
        root.insert(-1, transition)

    # Add playlists to root
    for playlist in playlists:
        root.insert(-1, playlist)

    # Add profile to the root of tree
    root.insert(0, profile_e)

    # Render the XML
    tree = minidom.parseString(et.tostring(root, 'utf-8'))

    return tree.toprettyxml(indent="    ")
