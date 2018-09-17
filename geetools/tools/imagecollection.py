# coding=utf-8
""" Module holding tools for ee.ImageCollections """
import ee
import ee.data
from . import date

if not ee.data._initialized:
    ee.Initialize()


def fill_with_last(collection):
    """ Fill masked values of each image pixel with the last available
    value

    :param collection: the collection that holds the images that will be filled
    :type collection: ee.ImageCollection
    :rtype: ee.ImageCollection
    """

    new = collection.sort('system:time_start', True)
    collist = new.toList(new.size())
    first = ee.Image(collist.get(0)).unmask()
    rest = collist.slice(1)

    def wrap(img, ini):
        ini = ee.List(ini)
        img = ee.Image(img)
        last = ee.Image(ini.get(-1))
        mask = img.mask().Not()
        last_masked = last.updateMask(mask)
        last2add = last_masked.unmask()
        img2add = img.unmask()
        added = img2add.add(last2add) \
            .set('system:index', ee.String(img.id()))

        props = img.propertyNames()
        condition = props.contains('system:time_start')

        final = ee.Image(ee.Algorithms.If(condition,
                                          added.set('system:time_start',
                                                    img.date().millis()),
                                          added))

        return ini.add(final.copyProperties(img))

    newcol = ee.List(rest.iterate(wrap, ee.List([first])))
    return ee.ImageCollection.fromImages(newcol)


def reduce_equal_interval(collection, region, reducer=None, start_date=None,
                          end_date=None, interval=30, unit='day',
                          qa_band=None):
    """ Reduce an ImageCollection into a new one that has one image per
        reduced interval, for example, one image per month.

    :param collection:
    :param region:
    :param reducer:
    :param start_date:
    :param end_date:
    :param interval:
    :param unit:
    :param qa_band:
    :return:
    """
    collection = collection.filterBounds(region)
    first = ee.Image(collection.sort('system:time_start').first())
    last = ee.Image(collection.sort('system:time_start', False).first())

    if not start_date:
        start_date = first.date()
    if not end_date:
        end_date = last.date()
    if not qa_band:
        qa_band = ee.String(ee.Image(collection.first()).bandNames().get(0))

    def apply_reducer(reducer, col):
        return ee.Image(col.reduce(reducer))

    def apply_function(func, col):
        return

    def default_function(col, qa_band):
        return ee.Image(col.qualityMosaic(qa_band))

    ranges = date.daterange_list(start_date, end_date, interval, unit)

    def over_ranges(drange, ini):
        ini = ee.List(ini)
        drange = ee.DateRange(drange)
        start = drange.start()
        end = drange.end()
        filtered = collection.filterDate(start, end)
        condition = ee.Number(filtered.size()).gt(0)
        def true():
            image = apply_function(reducer, filtered)\
                    .set('system:time_start', end.millis())
            result = ini.add(image)
            return result
        return ee.List(ee.Algorithms.If(condition, true(), ini))

    imlist = ee.List(ranges.iterate(over_ranges, ee.List([])))

    return ee.ImageCollection.fromImages(imlist)


def get_values(collection, geometry, reducer=ee.Reducer.mean(), scale=None,
               id='system:index', properties=None, side='server'):
    """ Return all values of all bands of an image collection in the
        specified geometry

    :param geometry: Point from where to get the info
    :type geometry: ee.Geometry
    :param scale: The scale to use in the reducer. It defaults to 10 due
        to the minimum scale available in EE (Sentinel 10m)
    :type scale: int
    :param id: image property that will be the key in the result dict
    :type id: str
    :param properties: image properties that will be added to the resulting
        dict
    :type properties: list
    :param side: 'server' or 'client' side
    :type side: str
    :return: Values of all bands in the ponit
    :rtype: dict
    """
    if not scale:
        # scale = minscale(ee.Image(self.first()))
        scale = 1
    else:
        scale = int(scale)

    propid = ee.Image(collection.first()).get(id).getInfo()
    def transform(eeobject):
        try: # Py2
            isstr = isinstance(propid, (str, unicode))
        except: # Py3
            isstr = isinstance(propid, (str))

        if isinstance(propid, (int, float)):
            return ee.Number(eeobject).format()
        elif isstr:
            return ee.String(eeobject)
        else:
            msg = 'property must be a number or string, found {}'
            raise ValueError(msg.format(type(propid)))


    if not properties:
        properties = []
    properties = ee.List(properties)

    def listval(img, it):
        theid = ee.String(transform(img.get(id)))
        values = img.reduceRegion(reducer, geometry, scale)
        values = ee.Dictionary(values)
        img_props = img.propertyNames()

        def add_properties(prop, ini):
            ini = ee.Dictionary(ini)
            condition = img_props.contains(prop)
            def true():
                value = img.get(prop)
                return ini.set(prop, value)
            # value = img.get(prop)
            # return ini.set(prop, value)
            return ee.Algorithms.If(condition, true(), ini)

        with_prop = ee.Dictionary(properties.iterate(add_properties, values))
        return ee.Dictionary(it).set(theid, with_prop)

    result = collection.iterate(listval, ee.Dictionary({}))
    result = ee.Dictionary(result)

    if side == 'server':
        return result
    elif side == 'client':
        return result.getInfo()
    else:
        raise ValueError("side parameter must be 'server' or 'client'")