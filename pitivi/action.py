# PiTiVi , Non-linear video editor
#
#       pitivi/action.py
#
# Copyright (c) 2009, Edward Hervey <bilboed@bilboed.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

"""
Pipeline actions
"""

"""@var states: Something
@type states: C{ActionState}"""
states = (STATE_NOT_ACTIVE,
          STATE_ACTIVE) = range(2)

from pitivi.signalinterface import Signallable
from pitivi.factories.base import SourceFactory, SinkFactory
import gst

# TODO : Create a convenience class for Links

# FIXME : define/document a proper hierarchy
class ActionError(Exception):
    pass

class Action(object, Signallable):
    """
    Pipeline action.

    Controls the elements of a L{Pipeline}, including their creation,
    activation, and linking.

    Subclasses can also offer higher-level actions that automatically create
    the Producers(s)/Consumer(s), thereby simplifying the work required to do
    a certain multimedia 'Action' (Ex: Automatically create the appropriate
    Consumer for rendering a producer stream to a file).

    @ivar state: Whether the action is active or not
    @type state: C{ActionState}
    @ivar producers: The producers controlled by this L{Action}.
    @type producers: List of L{SourceFactory}
    @ivar consumers: The consumers controlled by this L{Action}.
    @type consumers: List of L{SinkFactory}
    @ivar pipeline: The L{Pipeline} controlled by this L{Action}.
    @type pipeline: L{Pipeline}
    @cvar compatible_producers: The list of compatible factories that
    this L{Action} can handle as producers.
    @type compatible_producers: List of L{ObjectFactory} classes
    @cvar compatible_consumers: The list of compatible factories that
    this L{Action} can handle as consumers.
    @type compatible_consumers: List of L{ObjectFactory} classes
    @cvar queue_size: Default queueing size (in seconds) to use for links.
    """

    compatible_producers = [ SourceFactory ]
    compatible_consumers = [ SinkFactory ]

    queue_size = 1

    __signals__ = {
        "state-changed" : ["state"]
        }

    def __init__(self):
        self.state = STATE_NOT_ACTIVE
        self.producers = []
        self.consumers = []
        self.pipeline = None
        self._links = [] # list of (producer, consumer, prodstream, consstream)
        self._pending_links = [] # list of links that still need to be connected
        self._dyn_links = [] # list of links added at RunTime, will be removed when deactivated
        self._dynconsumers = [] # consumers that we added at RunTime

    #{ Activation methods

    def activate(self):
        """
        Activate the action.

        For each of the consumers/producers it will create the relevant
        GStreamer objects for the Pipeline (if they don't already exist).

        @precondition: Must be set to a L{Pipeline}
        @precondition: The Pipeline must be in the NULL/READY state.
        @precondition: All consumers/producers must be set on the L{Pipeline}.

        @return: Whether the L{Action} was activated (True) or not.
        @rtype: L{bool}
        @raise ActionError: If the L{Action} isn't set to a L{Pipeline}, or one
        of the consumers/producers isn't set on the Pipeline.
        @raise ActionError: If some producers or consumers remain unused.
        @raise PipelineError: If the L{Pipeline} is not in the NULL or READY
        state.
        """
        gst.debug("Activating...")
        if self.pipeline is None:
            raise ActionError("Action isn't set to a Pipeline")
        if self.state == STATE_ACTIVE:
            gst.debug("Action already activated, returning")
            return
        self._ensurePipelineObjects()
        self.state = STATE_ACTIVE
        self.emit('state-changed', self.state)
        gst.debug("... done activating")

    def deactivate(self):
        """
        De-activate the Action.

        @precondition: The associated L{Pipeline} must be in the NULL or READY
        state.

        @see: L{activate}

        @return: Whether the L{Action} was de-activated (True) or not.
        @rtype: L{bool}
        @raise PipelineError: If the L{Pipeline} is not in the NULL or READY
        state.
        """
        gst.debug("De-Activating...")
        if self.state == STATE_NOT_ACTIVE:
            raise ActionError()

        if self.pipeline == None:
            gst.warning("Attempting to deactivate Action without a Pipeline")
            # yes, gracefully return
            return
        self._releasePipelineObjects()
        self.state = STATE_NOT_ACTIVE
        self.emit('state-changed', self.state)
        gst.debug("... done de-activating")

    def isActive(self):
        """
        Whether the Action is active or not

        @see: L{activate}, L{deactivate}

        @return: True if the Action is active.
        @rtype: L{bool}
        """
        return self.state == STATE_ACTIVE

    #{ Pipeline methods

    def setPipeline(self, pipeline):
        """
        Set the L{Action} on the given L{Pipeline}.

        @param pipeline: The L{Pipeline} to set the L{Action} onto.
        @type pipeline: L{Pipeline}
        @warning: This method should only be used by L{Pipeline}s when the given
        L{Action} is set on them.
        @precondition: The L{Action} must not be set to any other L{Pipeline}
        when this method is called.
        @raise ActionError: If the L{Action} is active or the pipeline is set to
        a different L{Pipeline}.
        """
        if self.pipeline == pipeline:
            gst.debug("New pipeline is the same as the currently set one")
            return
        if self.pipeline != None:
            raise ActionError("Action already set to a Pipeline")
        if self.state != STATE_NOT_ACTIVE:
            raise ActionError("Action is active, can't change Pipeline")
        self.pipeline = pipeline

    def unsetPipeline(self):
        """
        Remove the L{Action} from the currently set L{Pipeline}.

        @see: L{setPipeline}

        @warning: This method should only be used by L{Pipeline}s when the given
        L{Action} is removed from them.
        @precondition: The L{Action} must be deactivated before it can be removed from a
        L{Pipeline}.
        @raise ActionError: If the L{Action} is active.
        """
        if self.state != STATE_NOT_ACTIVE:
            raise ActionError("Action is active, can't unset Pipeline")
        self.pipeline = None

    #{ ObjectFactory methods

    def addProducers(self, *producers):
        """
        Add the given L{ObjectFactory}s as producers of the L{Action}.

        @type producers: List of L{ObjectFactory}
        @raise ActionError: If the L{Action} is active.
        """
        gst.debug("producers:%r" % producers)
        if self.state != STATE_NOT_ACTIVE:
            raise ActionError("Action is active, can't add Producers")
        # make sure producers are of the valid type
        if self.compatible_producers != []:
            for p in producers:
                val = False
                for t in self.compatible_producers:
                    if isinstance(p, t):
                        val = True
                        continue
                if val == False:
                    raise ActionError("Some producers are not of the compatible type")
        for p in producers:
            if not p in self.producers:
                gst.debug("really adding %r to our producers" % p)
                self.producers.append(p)

    def removeProducers(self, *producers):
        """
        Remove the given L{ObjectFactory}s as producers of the L{Action}.

        @see: L{addProducers}

        @type producers: List of L{ObjectFactory}
        @raise ActionError: If the L{Action} is active.
        """
        if self.state != STATE_NOT_ACTIVE:
            raise ActionError("Action is active, can't remove Producers")
        # FIXME : figure out what to do in regards with links
        for p in producers:
            try:
                self.producers.remove(p)
            except ValueError:
                raise ActionError()

    def addConsumers(self, *consumers):
        """
        Set the given L{ObjectFactory}s as consumers of the L{Action}.

        @type consumers: List of L{ObjectFactory}
        @raise ActionError: If the L{Action} is active.
        """
        gst.debug("consumers: %r" % consumers)
        if self.state != STATE_NOT_ACTIVE:
            raise ActionError("Action is active, can't add Producers")
        # make sure consumers are of the valid type
        if self.compatible_consumers != []:
            for p in consumers:
                val = False
                for t in self.compatible_consumers:
                    if isinstance(p, t):
                        val = True
                        continue
                if val == False:
                    raise ActionError("Some consumers are not of the compatible type")
        for p in consumers:
            if not p in self.consumers:
                gst.debug("really adding %r to our consumers" % p)
                self.consumers.append(p)

    def removeConsumers(self, *consumers):
        """
        Remove the given L{ObjectFactory}s as consumers of the L{Action}.

        @see: L{addConsumers}
        @type consumers: List of L{ObjectFactory}
        @raise ActionError: If the L{Action} is active.
        """
        if self.state != STATE_NOT_ACTIVE:
            raise ActionError("Action is active, can't remove Consumers")
        # FIXME : figure out what to do in regards with links
        for p in consumers:
            try:
                self.consumers.remove(p)
            except ValueError:
                raise ActionError()

    #{ Link methods

    def setLink(self, producer, consumer, producerstream=None,
                consumerstream=None):
        """
        Set a relationship (link) between producer and consumer.

        If the Producer and/or Consumer isn't already set to this L{Action},
        this method will attempt to add them.

        @param producer: The producer we wish to link.
        @type producer: L{ObjectFactory}
        @param consumer: The consumer we wish to link.
        @type consumer: L{ObjectFactory}
        @param producerstream: The L{MultimediaStream} to use from the producer. If not
        specified, the L{Action} will figure out a compatible L{MultimediaStream} between
        the producer and consumer.
        @type producerstream: L{MultimediaStream}
        @param consumerstream: The L{MultimediaStream} to use from the consumer. If not
        specified, the L{Action} will figure out a compatible L{MultimediaStream} between
        the consumer and consumer.
        @type consumerstream: L{MultimediaStream}
        @raise ActionError: If the L{Action} is active.
        @raise ActionError: If the producerstream isn't available on the
        producer.
        @raise ActionError: If the consumerstream isn't available on the
        consumer.
        @raise ActionError: If the producer and consumer are incompatible.
        @raise ActionError: If the link is already set.
        """
        # If streams are specified, make sure they exist in their respective factories
        # Make sure producer and consumer are compatible
        # If needed, add producer and consumer to ourselves
        # store the link
        if self.isActive():
            raise ActionError("Can't add link when active")

        if producerstream is not None \
                and not producerstream in producer.getOutputStreams():
            raise ActionError("Stream specified isn't available in producer")
        if consumerstream is not None \
                and not consumerstream in consumer.getInputStreams():
            raise ActionError("Stream specified isn't available in consumer")

        # check if the streams are compatible
        if producerstream is not None and consumerstream is not None:
            if not producerstream.isCompatible(consumerstream):
                raise ActionError("Specified streams are not compatible")

        # finally check if that link isn't already set
        linktoadd = (producer, consumer, producerstream, consumerstream)
        if linktoadd in self._links:
            raise ActionError("Link already present")

        # now, lets' see if we are already controlling the consumer and producer
        if producer not in self.producers:
            self.addProducers(producer)
        if consumer not in self.consumers:
            self.addConsumers(consumer)
        self._links.append(linktoadd)

    def removeLink(self, producer, consumer, producerstream=None,
                   consumerstream=None):
        """
        Remove a relationship (link) between producer and consumer.

        @see: L{setLink}

        @param producer: The producer we wish to unlink.
        @type producer: L{ObjectFactory}
        @param consumer: The consumer we wish to unlink.
        @type consumer: L{ObjectFactory}
        @param producerstream: The L{MultimediaStream} to use from the producer. If not
        specified, the L{Action} will figure out a compatible L{MultimediaStream} between
        the producer and consumer.
        @type producerstream: L{MultimediaStream}.
        @param consumerstream: The L{MultimediaStream} to use from the consumer. If not
        specified, the L{Action} will figure out a compatible L{MultimediaStream} between
        the consumer and consumer.
        @type consumerstream: L{MultimediaStream}.
        @raise ActionError: If the L{Action} is active.
        @raise ActionError: If the link didn't exist
        """
        if self.isActive():
            raise ActionError("Action active")

        alink = (producer, consumer, producerstream, consumerstream)
        if not alink in self._links:
            raise ActionError("Link doesn't exist !")

        self._links.remove(alink)

    def getLinks(self, autolink=True):
        """
        Returns the Links setup for this Action.

        Sub-classes can override this to fine-tune the linking:
         - Specify streams of producers
         - Specify streams of consumers
         - Add Extra links

        Sub-classes should chain-up to the parent class method BEFORE doing
        anything with the link list.

        @param autolink: If True and there were no links specified previously by
        setLink(), then a list of Links will be automatically created based on
        the available producers, consumers and their respective streams.
        @type autolink: C{bool}
        @return: A list of Links
        @rtype: List of (C{Producer}, C{Consumer}, C{ProducerStream}, C{ConsumerStream})
        """
        links = self._links[:]
        if links == [] and autolink == True:
            links = self.autoLink()
        gst.debug("Returning %d links" % len(links))
        return links


    def autoLink(self):
        """
        Based on the available consumers and producers, returns a list of
        compatibles C{Link}s.

        Sub-classes can override this method (without chaining up) to do their
        own auto-linking algorithm, although it is more recommended to
        implement getLinks().

        @see: L{getLinks}
        @raise ActionError: If there is any ambiguity as to which producerstream
        should be linked to which consumerstream.
        @return: List of compatible Links.
        """
        gst.debug("Creating automatic links")
        links = []
        # iterate producers and their output streams
        for producer in self.producers:
            gst.debug("producer %r" % producer)
            for producer_stream in producer.getOutputStreams():
                gst.debug(" stream %r" % producer_stream)
                # for each, figure out a compatible (consumer, stream)
                for consumer in self.consumers:
                    gst.debug("  consumer %r" % consumer)
                    compat = consumer.getInputStreams(type(producer_stream))
                    # in case of ambiguity, raise an exception
                    if len(compat) > 1:
                        raise ActionError("Too many compatible streams in consumer")
                    if len(compat) == 1:
                        gst.debug("    Got a compatible stream !")
                        links.append((producer, consumer,
                                producer_stream, compat[0]))
        return links

    #{ Dynamic Stream handling

    def handleNewStream(self, producer, stream):
        """
        Handle the given stream of the given producer.

        Called by the Pipeline when one of the producers controlled by this
        action produces a new Stream

        Subclasses can override this method and chain-up to the parent class
        method *before* doing their own processing.

        @param producer: The producer of the stream
        @type producer: L{SourceFactory}
        @param stream: The new stream
        @type stream: L{MultimediaStream}
        @return: C{True} if the Stream is/was handled by the Action, else C{False}
        @rtype: C{bool}
        """
        gst.debug("producer:%r, stream:%r" % (producer, stream))

        waspending = False

        # 1. Check if it's one of our pendings pads
        pl = self._pending_links[:]
        for prod, cons, prodstream, consstream in pl:
            if prod == producer and (prodstream == None or \
                    prodstream.isCompatibleWithName(stream)):
                if self._activateLink(prod, cons, prodstream, consstream):
                    waspending = True
                    gst.debug("Successfully linked pending stream, removing "
                            "it from temp list")
                    self._pending_links.remove((prod, cons,
                            prodstream, consstream))

        if waspending == False:
            # 2. If it's not one of the pending links, It could also be one of the
            # links we've *already* handled
            for prod, cons, ps, cs in self.getLinks():
                if prod == producer and ps.isCompatibleWithName(stream):
                    return True

        # 3. Dynamic linking, ask if someone can handle this if nothing else did
        # up to now.
        for prod, cons, prodstream, consstream in self.getDynamicLinks(producer, stream):
            if not cons in self.consumers and not cons in self._dynconsumers:
                # we need to add that new consumer
                self._dynconsumers.append(cons)
            self._dyn_links.append((prod, cons, prodstream, consstream))
            waspending |= self._activateLink(prod, cons,
                    prodstream, consstream, init=False)

        gst.debug("returning %r" % waspending)
        return waspending

    def streamRemoved(self, producer, stream):
        """
        A stream has been removed from one of the producers controlled by this
        action.

        Called by the Pipeline.
        """
        link = None
        gst.debug("producer:%r, stream:%r" % (producer, stream))
        for dyn_producer, dyn_consumer, \
                dyn_producer_stream, dyn_consumer_stream in list(self._dyn_links):
            if producer != dyn_producer or stream != dyn_producer_stream:
                continue

            # release tee/queue usage for that stream
            self.pipeline.releaseQueueForFactoryStream(dyn_consumer,
                    dyn_consumer_stream)
            self.pipeline.releaseBinForFactoryStream(dyn_consumer,
                    dyn_consumer_stream)
            self.pipeline.releaseTeeForFactoryStream(dyn_producer,
                    dyn_producer_stream)
            self.pipeline.releaseBinForFactoryStream(dyn_producer,
                    dyn_producer_stream)

            self._dyn_links.remove((dyn_producer, dyn_consumer,
                    dyn_producer_stream, dyn_consumer_stream))
            break

    def getDynamicLinks(self, producer, stream):
        """
        Return a list of links to handle the given producer/stream.

        Subclasses can override this to give links for streams that appear
        dynamically and should chain up to the parent-class implementation
        BEFORE their own implementation (i.e. adding to the list they get).
        If new producers are given, they will be dynamically added to the
        C{Action} and the controlled C{Pipeline}.

        @param producer: A producer.
        @type producer: C{SourceFactory}
        @param stream: The stream to handle
        @type stream: C{MultimediaStream}
        @return: a list of links
        """
        return []
    #}

    def _ensurePipelineObjects(self):
        """
        Makes sure all objects needed in the pipeline are properly created.

        @precondition: All checks relative to pipeline/action/factory validity
        must be done.
        @raise ActionError: If some producers or consumers remain unused.
        """
        for producer in self.producers:
            self.pipeline.getBinForFactoryStream(producer, automake=True)

        # Get the links
        links = self.getLinks()
        # ensure all links are used
        cplinks = links[:]
        for producer, consumer, producer_stream, consumer_stream in links:
            if producer in self.producers and consumer in self.consumers:
                cplinks.remove((producer, consumer,
                        producer_stream, consumer_stream))

        if cplinks != []:
            raise ActionError("Some links are not used !")

        # clear dynamic-stream variables
        self._dyn_links = []
        self._pending_links = []
        self._dynconsumers = []

        for link in links:
            self._activateLink(*link)

    def _activateLink(self, producer, consumer, prodstream, consstream, init=True):
        # FIXME: we import PipelineError here to avoid a circular import
        from pitivi.pipeline import PipelineError

        # activate the given Link, returns True if it was (already) activated
        # if init is True, then remember the pending link
        gst.debug("producer:%r, consumer:%r, prodstream:%r, consstream:%r" % (\
                producer, consumer, prodstream, consstream))

        self.pipeline.getBinForFactoryStream(producer, prodstream)

        # Make sure we have tees for our (producer,stream)s
        try:
            tee = self.pipeline.getTeeForFactoryStream(producer, prodstream,
                                                     automake=True)
        except PipelineError:
            if init != True:
                gst.debug("Could not create link")
                return False

            gst.debug("Stream will be created dynamically")
            self._pending_links.append((producer, consumer, prodstream, consstream))
            return True

        # Make sure we have a bin for our consumer
        bin = self.pipeline.getBinForFactoryStream(consumer,
                consstream, automake=True)

        if init != True:
            # we set the sink to paused, since we are adding this link during
            # auto-plugging
            bin.set_state(gst.STATE_PAUSED)

        # Make sure we have queues for our (consumer, stream)s
        queue = self.pipeline.getQueueForFactoryStream(consumer, consstream,
                                                       automake=True, queuesize=self.queue_size)

        # FIXME: where should this be unlinked?
        """
        sinkpad = q.get_pad('sink')
        if sinkpad.is_linked():
            sinkpad.get_peer().unlink(sinkpad)
        """

        # Link tees to queues
        tee.link(queue)

        return True

    def _releasePipelineObjects(self):
        from pitivi.pipeline import PipelineError
        gst.debug("Releasing pipeline objects")
        for producer, consumer, prodstream, consstream in self.getLinks():
            # release tee/queue usage for that stream
            self.pipeline.releaseQueueForFactoryStream(consumer, consstream)
            self.pipeline.releaseBinForFactoryStream(consumer, consstream)
            self.pipeline.releaseTeeForFactoryStream(producer, prodstream)
            self.pipeline.releaseBinForFactoryStream(producer, prodstream)

        # release dynamic links
        for producer, consumer, prodstream, consstream in self._dyn_links:
            # release tee/queue usage for that stream
            self.pipeline.releaseQueueForFactoryStream(consumer, consstream)
            self.pipeline.releaseBinForFactoryStream(consumer, consstream)
            self.pipeline.releaseTeeForFactoryStream(producer, prodstream)
            self.pipeline.releaseBinForFactoryStream(producer, prodstream)
        self._dyn_links = []

        # try to clean producers that were never linked, if any
        for producer in self.producers:
            try:
                self.pipeline.releaseBinForFactoryStream(producer)
            except PipelineError:
                # FIXME: use a strictier exception hierarchy
                pass

class ViewAction(Action):
    """
    An action used to view sources.

    Will automatically connect stream from the controlled producer to the given
    sinks.
    """
    # FIXME : how to get default handlers ?
    # ==> Use plumber in the meantime
    # FIXME : How to handle multiple video sinks (and XID) ?

    def __init__(self, *args, **kwargs):
        gst.debug("Creating new ViewAction")
        Action.__init__(self, *args, **kwargs)
        self.videosink = None
        self.audiosink = None
        self.xid = 0

    def getDynamicLinks(self, producer, stream):
        gst.debug("producer:%r, stream:%r" % (producer, stream))
        import plumber
        from pitivi.stream import AudioStream, VideoStream
        res = Action.getDynamicLinks(self, producer, stream)
        if isinstance(stream, VideoStream):
            consumer = plumber.DefaultVideoSink()
            self.videosink = consumer
            if self.xid != 0:
                self.videosink.set_window_xid(self.xid)

            res.append((producer, consumer, stream, None))
        elif isinstance(stream, AudioStream):
            consumer = plumber.DefaultAudioSink()
            self.audiosink = consumer
            res.append((producer, consumer, stream, None))
        return res

    def set_window_xid(self, xid):
        """
        Set the XID where the video consumer should display.
        """
        gst.debug("xid:%r" % xid)
        # FIXME : What if we have several video sinks ???
        self.xid = xid
        if self.videosink:
            self.videosink.set_window_xid(self.xid)


class RenderAction(Action):
    """
    An Action to render sources.

    Handles both a L{RenderFactory} and a L{SinkFactory}.
    """

    def __init__(self, *args, **kwargs):
        Action.__init__(self, *args, **kwargs)
        self.renderfactory = None
        self.sinkfactory = None
