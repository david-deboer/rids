from __future__ import print_function
import json
import os
import numpy as np
import gzip
import rids_utils as utils
import peaks


class Spectral:
    def __init__(self, polarization='', comment=''):
        self.comment = comment
        self.polarization = polarization
        self.freq = []
        self.val = []


class Rids:
    """
    RF Interference Data System (RIDS)
    Reads/writes .rids/[.ridz] files, [zipped] JSON files with fields as described below.
    Any field may be omitted or missing.
      This first set is header information - typically stored in a .rids file that gets read/rewritten
        instrument:  description of the instrument used
        receiver:  description of receiver used
        channel_width:  RF bandwidth
        channel_width_unit:  unit of bandwidth
        vbw: video bandwidth (typically used for spectrum analyzer)
        vbw_unit: unit of bandwidth
        time_constant: averaging time/maxhold reset time
            though not ideal, can be a descriptive word or word pair for e.g. ongoing maxhold, etc
        time_constant_unit:  unit of time_constant
        threshold:  value used to threshold peaks
        threshold_unit: unit of threshold
        freq_unit:  unit of frequency used in spectra
        val_unit: unit of value used in spectra
        comment:  general comment
      These are typically set in data-taking session
        time_stamp:  time_stamp for file/baseline data
        cal:  calibration data by polarization/frequency
        events:  baseline or ave/maxhold spectra
    """
    dattr = ['instrument', 'receiver', 'time_stamp', 'freq_unit', 'val_unit']
    uattr = ['channel_width', 'time_constant', 'threshold', 'vbw']
    spectral_fields = ['comment', 'polarization', 'freq', 'val', 'ave', 'maxhold']
    polarizations = ['E', 'N']

    def __init__(self, comment=None):
        self.instrument = None
        self.receiver = None
        self.channel_width = None
        self.channel_width_unit = None
        self.vbw = None
        self.vbw_unit = None
        self.time_constant = None
        self.time_constant_unit = None
        self.threshold = None
        self.threshold_unit = None
        self.freq_unit = None
        self.val_unit = None
        self.comment = comment
        self.time_stamp = None
        self.cal = {}
        for pol in self.polarizations:
            self.cal[pol] = Spectral(polarization=pol)
        self.events = {}
        # --Other variables--
        self.hipk = None

    def rid_reader(self, filename):
        """
        This will read a RID file with a full or subset of structure entities
        """
        file_type = filename.split('.')[-1].lower()
        if file_type == 'ridz':
            r_open = gzip.open
        else:
            r_open = open
        with r_open(filename, 'rb') as f:
            data = json.load(f)
        if 'comment' in data:
            self.append_comment(data['comment'])
        for d in self.dattr:
            if d in data:
                setattr(self, d, data[d])
        for d in self.uattr:
            if d in data:
                self._set_uattr(d, data[d])
        if 'cal' in data:
            for pol in self.polarizations:
                if pol in data['cal']:
                    for v in self.spectral_fields:
                        if v in data['cal'][pol]:
                            setattr(self.cal[pol], v, data['cal'][pol][v])
        if 'events' in data:
            for d in data['events']:
                self.events[d] = Spectral()
                for v in self.spectral_fields:
                    if v in data['events'][d]:
                        setattr(self.events[d], v, data['events'][d][v])

    def _set_uattr(self, d, x):
        v = x.split()
        if len(v) == 1:
            d0 = v[0]
            d1 = None
        elif len(v) > 1:
            try:
                d0 = float(v[0])
            except ValueError:
                d0 = v[0]
            d1 = v[1]
        setattr(self, d, d0)
        setattr(self, d + '_unit', d1)

    def rid_writer(self, filename, fix_list=True):
        """
        This writes a RID file with a full structure
        """
        ds = {}
        ds['comment'] = self.comment
        for d in self.dattr:
            ds[d] = getattr(self, d)
        for d in self.uattr:
            ds[d] = "{} {}".format(getattr(self, d), getattr(self, d + '_unit'))
        ds['cal'] = {'E': {}, 'N': {}}
        for pol in self.polarizations:
            for v in self.spectral_fields:
                try:
                    ds['cal'][pol][v] = getattr(self.cal[pol], v)
                except AttributeError:
                    continue
        ds['events'] = {}
        for d in self.events:
            ds['events'][d] = {}
            for v in self.spectral_fields:
                try:
                    ds['events'][d][v] = getattr(self.events[d], v)
                except AttributeError:
                    continue
        jsd = json.dumps(ds, sort_keys=True, indent=4, separators=(',', ':'))
        if fix_list:
            jsd = utils.fix_json_list(jsd)
        file_type = filename.split('.')[-1].lower()
        if file_type == 'ridz':
            r_open = gzip.open
        else:
            r_open = open
        with r_open(filename, 'wb') as f:
            f.write(jsd)

    def set(self, **kwargs):
        for k in kwargs:
            if k in self.dattr:
                setattr(self, k, kwargs[k])
            elif k in self.uattr:
                self._set_uattr(k, kwargs[k])

    def append_comment(self, comment):
        if comment is None:
            return
        if self.comment is None:
            self.comment = comment
        else:
            self.comment += ('\n' + comment)

    def get_event(self, event, ave_fn, maxhold_fn, polarization):
        ave = Spectral()
        utils.spectrum_reader(ave_fn, ave, polarization)
        maxhold = Spectral()
        utils.spectrum_reader(maxhold_fn, maxhold, polarization)
        self.events[event] = Spectral(polarization=polarization)
        if 'baseline' in event.lower():
            self.events[event].freq = ave.freq if len(ave.freq) > len(maxhold.freq) else maxhold.freq
            self.events[event].ave = ave.val
            self.events[event].maxhold = maxhold.val
        else:
            self.peak_finder(maxhold)
            self.events[event].freq = list(np.array(maxhold.freq)[self.hipk])
            try:
                self.events[event].ave = list(np.array(ave.val)[self.hipk])
            except IndexError:
                pass
            self.events[event].maxhold = list(np.array(maxhold.val)[self.hipk])

    def peak_finder(self, spec, cwt_range=[1, 7], rc_range=[4, 4]):
        self.hipk_freq = spec.freq
        self.hipk_val = spec.val
        self.hipk = peaks.fp(spec.val, self.threshold, cwt_range, rc_range)

    def peak_viewer(self):
        if self.hipk is None:
            print("No peaks sought.")
            return
        import matplotlib.pyplot as plt
        plt.plot(self.hipk_freq, self.hipk_val)
        plt.plot(np.array(self.hipk_freq)[self.hipk], np.array(self.hipk_val)[self.hipk], 'kv')

    def viewer(self):
        import matplotlib.pyplot as plt
        clr = ['k', 'b', 'g', 'r', 'm', 'c', 'y']
        c = 0
        for e, v in self.events.iteritems():
            if 'baseline' in e:
                plt.plot(v.freq[:len(v.ave)], v.ave, 'k')
                plt.plot(v.freq, v.maxhold, 'k')
            else:
                s = clr[c % len(clr)]
                plt.plot(v.freq[:len(v.ave)], v.ave[:len(v.freq)], s + '_')
                plt.plot(v.freq, v.maxhold, s + 'v')
                c += 1

    def stats(self):
        print("Provide standard set of occupancy etc stats")

    def process_files(self, directory, obs_per_file=100, max_loops=1000):
        loop = True
        max_loop_ctr = 0
        while (loop):
            max_loop_ctr += 1
            if max_loop_ctr > max_loops:
                break
            available_files = sorted(os.listdir(directory))
            f = {'ave': {'E': [], 'N': []},
                 'maxh': {'E': [], 'N': []}}
            loop = False
            for af in available_files:
                ftype, pol = utils.peel_type_polarization(af)
                if ftype in ['ave', 'maxh']:
                    loop = True
                    f[ftype][pol].append(os.path.join(directory, af))
            for pol in self.polarizations:
                if not len(f['ave'][pol]) or not len(f['maxh'][pol]):
                    continue
                elif len(f['ave'][pol]) != len(f['maxh'][pol]):
                    continue
                time_stamp = utils.peel_time_stamp(f['ave'][pol][0])
                self.set(time_stamp=time_stamp)
                self.get_event('baseline_' + pol, f['ave'][pol][0], f['maxh'][pol][0], pol)
                for a, m in zip(f['ave'][pol][:obs_per_file], f['maxh'][pol][:obs_per_file]):
                    time_stamp = utils.peel_time_stamp(a) + pol
                    self.get_event(time_stamp, a, m, pol)
                    os.remove(a)
                    os.remove(m)
            output_file = os.path.join(directory, str(self.time_stamp) + '.ridz')
            self.rid_writer(output_file)
