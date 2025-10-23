#!/usr/bin/env python3
"""Calibration utilities extracted from Naive_Single_LO_Per_Filt_Calib_Arduino.py
"""
import numpy as np
from astropy.io import fits


def makeSingleListOfInts(a1, a2, a3):
	ADC1, ADC2, ADC3 = list(), list(), list()
	for i in range(len(a1)):
		ADC1.append(int(a1[i]))
		ADC2.append(int(a2[i]))
		ADC3.append(int(a3[i]))
	return ADC1 + ADC2 + ADC3


def toVolts(data):
	adjustedData = []
	REF = 5 #3.27
	for i in data:
		if (i >> 31) == 1:
			divisor = 2**31
			adjustedData.append(REF * 2 - i/divisor * REF)
		else:
			divisor = 2**31 - 1
			adjustedData.append(i/divisor * REF)
	return adjustedData

def calibrationCurve(dataFits, pwrSetting):
	calDict = dict()
	startIdx = 20
	for fltIdx in range (startIdx, 281, 13):
		fltNum = int((fltIdx-startIdx)/13)
		loFreq = int(float(dataFits[fltIdx][5]) * 10) / 10
		a1, a2, a3 = dataFits[fltIdx][0][:7], dataFits[fltIdx][1][:7], dataFits[fltIdx][2][:7]
		combinedInts = makeSingleListOfInts(a1, a2, a3)
		sweepVolts = toVolts(combinedInts)
		detVolts = sweepVolts[fltNum]
		yint = detVolts + 0.025 * (pwrSetting)
		slopeTrue = (1 / - 0.025)
		yintTrue = - (yint / - 0.025)
		calDict[fltNum] = (loFreq, slopeTrue, yintTrue)
	print("LENGTH:",len(calDict))
	return calDict


def toDB(sweepData, calDict):
	DBData = []
	for fltIdx in range(21):
		DBData.append(calDict[fltIdx][1] * sweepData[fltIdx] + calDict[fltIdx][2])
	return DBData
